"""工程工作区 Hybrid 检索服务。

生产级实现：
    - Corpus 从真实上传文件构建（PDF/Excel/Markdown）
    - 仅 confirmed role 文件进入 Corpus
    - corpus_manifest.json 校验跨 workspace/owner 隔离
    - 原子写入 NPZ + metadata + manifest
    - 统一 EngineeringRetrievalError 异常体系
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_chunk import FileChunk
from app.models.file_profile import FileProfile
from app.models.workspace_file import WorkspaceFile
from app.retrieval.bm25 import BM25Scorer
from app.retrieval.dense_index import (
    DenseIndexError,
    _resolve_active_assets,
    load_dense_index,
    validate_index_exists,
)
from app.retrieval.embedding import (
    MODEL_REPO_ID,
    MODEL_REVISION,
    QUERY_INSTRUCTION,
    EmbeddingError,
    LocalEmbeddingProvider,
)
from app.retrieval.errors import (
    EngineeringRetrievalError,
    index_error,
    index_missing,
    index_stale,
    material_not_ready,
    model_unavailable,
)
from app.retrieval.hybrid import RRF_K, hybrid_rrf_retrieve
from app.retrieval.schemas import (
    ENGINEERING_ROLES,
    CorpusChunk,
    IndexInfo,
    RetrievalResult,
    SearchResponse,
)
from app.services.engineering_corpus_adapter import build_corpus_from_files

# ── 索引存储路径 ──────────────────────────────────────────────────────
_INDEX_ROOT = Path(__file__).resolve().parents[2] / "storage" / "retrieval" / "workspaces"


def _index_dir(workspace_id: int) -> Path:
    return _INDEX_ROOT / str(workspace_id)


def _make_provider(model_cache_dir: str | None) -> LocalEmbeddingProvider:
    """创建并加载 Embedding provider。

    模型不可用时抛出 ENGINEERING_RETRIEVAL_MODEL_UNAVAILABLE（500），
    不泄露模型缓存路径、系统路径或堆栈。
    """
    try:
        provider = LocalEmbeddingProvider(cache_dir=model_cache_dir)
        provider._ensure_loaded()
        return provider
    except EmbeddingError as e:
        raise model_unavailable("Embedding 模型不可用，请稍后重试") from e


# ── 语料构建 ─────────────────────────────────────────────────────────


def _get_confirmed_role(db: Session, workspace_id: int, file_id: int) -> str | None:
    """获取文件的 confirmed role。

    优先级：
    1. WorkspaceFile.user_confirmed_role
    2. 最新 FileProfile.confirmed_role

    不使用 suggested_role 或 WorkspaceFile.file_role。
    """
    wf = db.scalar(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.file_id == file_id,
        )
    )
    if wf and wf.user_confirmed_role and wf.user_confirmed_role in ENGINEERING_ROLES:
        return wf.user_confirmed_role

    # 查找最新 ready profile 的 confirmed_role
    profile = db.scalar(
        select(FileProfile).where(
            FileProfile.workspace_id == workspace_id,
            FileProfile.file_id == file_id,
            FileProfile.status == "ready",
        ).order_by(FileProfile.profile_version.desc())
    )
    if profile and profile.confirmed_role and profile.confirmed_role in ENGINEERING_ROLES:
        return profile.confirmed_role

    return None


def _collect_file_infos(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """收集工作区中所有可用于检索的文件信息。

    只有同时满足以下条件的文件才进入 Corpus：
    - FileProfile 最新版本 status == ready
    - 用户已确认工程角色（confirmed_role 在 ENGINEERING_ROLES 中）

    返回 (files_info, warnings)。
    """
    ws_files = db.scalars(
        select(WorkspaceFile).where(WorkspaceFile.workspace_id == workspace_id)
    ).all()

    if not ws_files:
        return [], ["工作区没有关联文件"]

    file_ids = [wf.file_id for wf in ws_files]
    files_map: dict[int, File] = {}
    for f_obj in db.scalars(select(File).where(File.id.in_(file_ids))):
        files_map[f_obj.id] = f_obj

    warnings: list[str] = []
    files_info: list[dict[str, Any]] = []

    for wf in ws_files:
        fid = wf.file_id
        file_obj = files_map.get(fid)
        if file_obj is None:
            warnings.append(f"文件 {fid} 不存在，跳过")
            continue

        # 强制 confirmed role
        confirmed_role = _get_confirmed_role(db, workspace_id, fid)
        if confirmed_role is None:
            warnings.append(
                f"文件 {fid} ({file_obj.filename}) 未确认工程角色，跳过"
            )
            continue

        # 强制 ready profile
        profile = db.scalar(
            select(FileProfile).where(
                FileProfile.workspace_id == workspace_id,
                FileProfile.file_id == fid,
                FileProfile.status == "ready",
            ).order_by(FileProfile.profile_version.desc())
        )
        if profile is None:
            warnings.append(
                f"文件 {fid} ({file_obj.filename}) 没有 ready profile，跳过"
            )
            continue

        # 收集 OCR chunks（扫描 PDF 场景）
        ocr_chunks: list[dict[str, Any]] | None = None
        if file_obj.file_type == "pdf":
            ocr_records = db.scalars(
                select(FileChunk).where(
                    FileChunk.file_id == fid,
                    FileChunk.source_type == "scanned_pdf_ocr",
                ).order_by(FileChunk.chunk_index)
            ).all()
            if ocr_records:
                ocr_chunks = [
                    {
                        "page_number": fc.page_number,
                        "chunk_index": fc.chunk_index,
                        "chunk_text": fc.chunk_text,
                        "parser_version": fc.parser_version,
                    }
                    for fc in ocr_records
                ]

        files_info.append({
            "file_id": fid,
            "file_name": file_obj.filename,
            "file_type": file_obj.file_type or "unknown",
            "file_path": file_obj.file_path,
            "confirmed_role": confirmed_role,
            "ocr_chunks": ocr_chunks,
        })

    return files_info, warnings


def build_workspace_corpus(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
) -> tuple[list[CorpusChunk], list[str]]:
    """从真实上传文件构建 Corpus。

    返回 (chunks, warnings)。
    """
    files_info, warnings = _collect_file_infos(db, workspace_id, owner_user_id)
    if not files_info:
        return [], warnings

    chunks, adapter_warnings = build_corpus_from_files(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        files_info=files_info,
    )
    warnings.extend(adapter_warnings)

    if not chunks:
        return [], warnings

    chunks.sort(key=lambda c: c.chunk_id)
    return chunks, warnings


# ── Manifest 管理 ─────────────────────────────────────────────────────


def _build_manifest(
    workspace_id: int,
    owner_user_id: int,
    corpus_sha256: str,
    chunks: list[CorpusChunk],
    provider_meta: dict[str, Any],
    chunking_version: str = "1.0.0",
) -> dict[str, Any]:
    """Build corpus_manifest.json content."""
    file_ids = sorted(set(c.file_id for c in chunks))
    file_roles: dict[int, str] = {}
    for c in chunks:
        file_roles[c.file_id] = c.file_role

    return {
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "corpus_sha256": corpus_sha256,
        "chunk_count": len(chunks),
        "chunk_ids": [c.chunk_id for c in chunks],
        "file_ids": file_ids,
        "confirmed_roles": file_roles,
        "locator_summary": {
            "pdf_page": sum(1 for c in chunks if c.locator_type == "pdf_page"),
            "spreadsheet_cell": sum(1 for c in chunks if c.locator_type == "spreadsheet_cell"),
            "text_chunk": sum(1 for c in chunks if c.locator_type == "text_chunk"),
        },
        "parser_versions": sorted(set(c.parser_version for c in chunks)),
        "model_repo_id": provider_meta.get("model_repo_id", "unknown"),
        "model_revision": provider_meta.get("model_revision", "unknown"),
        "chunking_version": chunking_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _validate_manifest(
    manifest: dict[str, Any],
    workspace_id: int,
    owner_user_id: int,
    corpus_sha256: str,
    expected_chunk_ids: list[str],
    expected_file_ids: set[int],
    expected_roles: dict[int, str],
) -> list[str]:
    """Validate manifest against current state. Returns error descriptions."""
    errors: list[str] = []
    if manifest.get("workspace_id") != workspace_id:
        errors.append("workspace_id 不一致")
    if manifest.get("owner_user_id") != owner_user_id:
        errors.append("owner_user_id 不一致")
    if manifest.get("corpus_sha256") != corpus_sha256:
        errors.append("corpus_sha256 不一致")
    if manifest.get("chunk_ids", []) != expected_chunk_ids:
        errors.append("chunk_ids 不一致")
    stored_file_ids = set(manifest.get("file_ids", []))
    if stored_file_ids != expected_file_ids:
        errors.append("file_ids 不一致")
    stored_roles = manifest.get("confirmed_roles", {})
    # Convert keys to int for comparison
    stored_roles_int = {int(k): v for k, v in stored_roles.items()}
    if stored_roles_int != expected_roles:
        errors.append("confirmed_roles 不一致")
    return errors


def _validate_manifest_or_raise(
    idx_dir: Path,
    workspace_id: int,
    owner_user_id: int,
    corpus_sha256: str,
    expected_chunk_ids: list[str],
    expected_file_ids: set[int],
    expected_roles: dict[int, str],
) -> dict[str, Any]:
    """Validate manifest, raising index_stale on mismatch."""
    assets = _resolve_active_assets(idx_dir)
    if assets is None:
        raise index_stale("索引资产缺失或快照不一致，请重建索引")
    manifest_path = assets["manifest"]
    if not manifest_path.exists():
        raise index_stale("corpus_manifest.json 缺失，请重建索引")

    try:
        manifest = json.loads(manifest_path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        raise index_stale("corpus_manifest.json 损坏，请重建索引")

    errs = _validate_manifest(
        manifest, workspace_id, owner_user_id,
        corpus_sha256, expected_chunk_ids, expected_file_ids, expected_roles,
    )
    if errs:
        raise index_stale(f"Manifest 校验失败: {'; '.join(errs)}，请重建索引")

    return manifest


# ── 原子写入 ──────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, content: dict[str, Any]) -> None:
    """原子写入 JSON 文件：临时文件→写入→flush→os.replace。"""
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".json.tmp", prefix=".", dir=path.parent
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.replace(tmp_path, path)


def _atomic_write_npz(path: Path, embeddings: np.ndarray) -> str:
    """原子写入 NPZ 文件：临时文件→写入→flush→os.replace。返回 SHA-256。

    注意：np.savez_compressed 要求文件扩展名为 .npz，否则静默写入 0 字节。
    """
    # 使用 .npz 扩展名创建临时文件（numpy 需要 .npz 扩展名才能正确写入）
    import uuid
    tmp_path = path.parent / f".{uuid.uuid4().hex}.npz"
    try:
        np.savez_compressed(str(tmp_path), embeddings=embeddings)
        npz_sha = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    os.replace(str(tmp_path), str(path))
    return npz_sha


# ── 索引管理 ──────────────────────────────────────────────────────────


def get_index_status(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
) -> IndexInfo:
    """获取索引状态（不构建索引）。"""
    idx_dir = _index_dir(workspace_id)
    corpus, warnings = build_workspace_corpus(db, workspace_id, owner_user_id)

    if not corpus:
        return IndexInfo(
            status="empty",
            workspace_id=workspace_id,
            warnings=warnings,
        )

    corpus_sha256 = CorpusChunk.compute_corpus_sha256(corpus)
    file_ids = sorted(set(c.file_id for c in corpus))

    assets = _resolve_active_assets(idx_dir)
    if assets is not None:
        meta_path = assets["meta"]
        manifest_path = assets["manifest"]
        if not manifest_path.exists():
            return IndexInfo(
                status="stale",
                workspace_id=workspace_id,
                corpus_sha256=corpus_sha256,
                chunk_count=len(corpus),
                file_count=len(file_ids),
                warnings=warnings + ["corpus_manifest.json 缺失"],
            )
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            if meta.get("corpus_sha256") == corpus_sha256:
                return IndexInfo(
                    status="ready",
                    workspace_id=workspace_id,
                    corpus_sha256=corpus_sha256,
                    chunk_count=len(corpus),
                    file_count=len(file_ids),
                    model_repo_id=meta.get("model_repo_id", ""),
                    model_revision=meta.get("model_revision", ""),
                    index_sha256=meta.get("index_sha256", ""),
                    created_at=meta.get("created_at", ""),
                    warnings=warnings,
                )
            else:
                return IndexInfo(
                    status="stale",
                    workspace_id=workspace_id,
                    corpus_sha256=corpus_sha256,
                    chunk_count=len(corpus),
                    file_count=len(file_ids),
                    warnings=warnings + ["语料已变更，索引需重建"],
                )
        except (json.JSONDecodeError, OSError):
            return IndexInfo(
                status="stale",
                workspace_id=workspace_id,
                chunk_count=len(corpus),
                file_count=len(file_ids),
                warnings=warnings + ["索引元数据损坏，需重建"],
            )

    return IndexInfo(
        status="not_built",
        workspace_id=workspace_id,
        corpus_sha256=corpus_sha256,
        chunk_count=len(corpus),
        file_count=len(file_ids),
        warnings=warnings,
    )


def rebuild_index(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    model_cache_dir: str | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """构建/重建 Dense Index + corpus_manifest.json。

    步骤：
    1. 从真实文件构建 corpus
    2. 加载 embedding 模型
    3. 编码所有 chunk text
    4. 生成带唯一版本标识的一组资产文件
    5. 最后原子替换当前版本指针（current_version.json）完成提交

    任何步骤失败都只清理本次构建产生的文件，不触碰旧快照，
    保证构建失败时旧的三个索引资产仍能一起加载。
    """
    corpus, warnings = build_workspace_corpus(db, workspace_id, owner_user_id)
    if not corpus:
        raise material_not_ready("工作区没有可用于构建索引的工程材料")

    idx_dir = _index_dir(workspace_id)
    idx_dir.mkdir(parents=True, exist_ok=True)
    corpus_sha256 = CorpusChunk.compute_corpus_sha256(corpus)

    if not rebuild:
        assets = _resolve_active_assets(idx_dir)
        if assets is not None:
            try:
                meta = json.loads(assets["meta"].read_text("utf-8"))
                if meta.get("corpus_sha256") == corpus_sha256:
                    return {
                        "status": "already_built",
                        "workspace_id": workspace_id,
                        "corpus_sha256": corpus_sha256,
                        "chunk_count": len(corpus),
                        "index_sha256": meta.get("index_sha256", ""),
                        "warnings": warnings,
                    }
            except (json.JSONDecodeError, OSError):
                pass

    t0 = time.perf_counter()

    # 加载模型
    provider = _make_provider(model_cache_dir)
    provider_meta = provider.metadata()

    # 编码所有 chunk
    texts = [c.text for c in corpus]
    chunk_ids = [c.chunk_id for c in corpus]
    try:
        embeddings = provider.encode_passages(texts)
    except EmbeddingError as e:
        raise model_unavailable("Embedding 模型不可用，请稍后重试") from e

    chunking_version = "1.0.0"

    # 生成唯一版本标识，构建带版本标识的一组资产文件
    version = uuid.uuid4().hex
    staged_npz = idx_dir / f".{version}.npz"
    staged_meta = idx_dir / f".{version}.meta.json"
    staged_manifest = idx_dir / f".{version}.manifest.json"
    final_npz = idx_dir / f"dense_index_{version}.npz"
    final_meta = idx_dir / f"dense_index_meta_{version}.json"
    final_manifest = idx_dir / f"corpus_manifest_{version}.json"

    created: list[Path] = []
    try:
        # 1. 写入暂存文件（唯一文件名，不会覆盖任何现有资产）
        npz_sha = _atomic_write_npz(staged_npz, embeddings)
        created.append(staged_npz)

        meta = {
            "corpus_sha256": corpus_sha256,
            "model_repo_id": provider_meta.get("model_repo_id", "unknown"),
            "model_revision": provider_meta.get("model_revision", "unknown"),
            "embedding_dimension": int(embeddings.shape[1]),
            "chunk_count": len(chunk_ids),
            "chunk_ids": list(chunk_ids),
            "normalize_embeddings": provider_meta.get("normalize_embeddings", True),
            "query_instruction": provider_meta.get("query_instruction", ""),
            "chunking_version": chunking_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index_sha256": npz_sha,
            "dtype": "float32",
            "provider": provider_meta.get("provider", "unknown"),
            "device": provider_meta.get("device", "cpu"),
        }
        _atomic_write_json(staged_meta, meta)
        created.append(staged_meta)

        manifest = _build_manifest(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            corpus_sha256=corpus_sha256,
            chunks=corpus,
            provider_meta=provider_meta,
            chunking_version=chunking_version,
        )
        _atomic_write_json(staged_manifest, manifest)
        created.append(staged_manifest)

        # 2. 暂存文件改名为带版本标识的正式资产文件（此时旧快照仍生效）
        for src, dst in (
            (staged_npz, final_npz),
            (staged_meta, final_meta),
            (staged_manifest, final_manifest),
        ):
            os.replace(src, dst)
            created.append(dst)

        # 3. 最后原子替换当前版本指针（唯一的提交点）
        _atomic_write_json(idx_dir / "current_version.json", {
            "version": version,
            "npz": final_npz.name,
            "meta": final_meta.name,
            "manifest": final_manifest.name,
        })
    except Exception:
        # 失败：只清理本次构建产生的文件，旧快照保持完整
        for p in created:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    build_time_ms = (time.perf_counter() - t0) * 1000

    return {
        "status": "built",
        "workspace_id": workspace_id,
        "corpus_sha256": corpus_sha256,
        "chunk_count": len(corpus),
        "file_count": len(set(c.file_id for c in corpus)),
        "index_sha256": npz_sha,
        "model_repo_id": MODEL_REPO_ID,
        "model_revision": MODEL_REVISION,
        "build_time_ms": round(build_time_ms, 1),
        "warnings": warnings,
    }


# ── 检索 ──────────────────────────────────────────────────────────────


def search_workspace(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    query: str,
    top_k: int = 5,
    retrieval_mode: str = "hybrid_rrf",
    model_cache_dir: str | None = None,
) -> SearchResponse:
    """对工作区执行检索。"""
    corpus, _warnings = build_workspace_corpus(db, workspace_id, owner_user_id)
    if not corpus:
        return SearchResponse(
            query=query,
            retrieval_mode=retrieval_mode,
            results=[],
        )

    idx_dir = _index_dir(workspace_id)
    corpus_sha256 = CorpusChunk.compute_corpus_sha256(corpus)
    chunk_ids_corpus_order = [c.chunk_id for c in corpus]
    expected_file_ids = set(c.file_id for c in corpus)
    expected_roles: dict[int, str] = {}
    for c in corpus:
        expected_roles[c.file_id] = c.file_role

    t0 = time.perf_counter()
    latencies: dict[str, float] = {}

    corpus_dicts = [c.to_retrieval_dict() for c in corpus]

    if retrieval_mode == "bm25":
        scorer = BM25Scorer(corpus_dicts)
        scores = scorer.score(query)
        t1 = time.perf_counter()
        latencies["bm25_ms"] = round((t1 - t0) * 1000, 1)

        results: list[RetrievalResult] = []
        for rank, (cid, bm_score) in enumerate(scores[:top_k], start=1):
            chunk = next((c for c in corpus if c.chunk_id == cid), None)
            if chunk is None:
                continue
            results.append(
                RetrievalResult(
                    rank=rank,
                    chunk_id=cid,
                    file_id=chunk.file_id,
                    file_name=chunk.file_name,
                    file_role=chunk.file_role,
                    locator_type=chunk.locator_type,
                    quote=_truncate_quote(chunk.text),
                    score=bm_score,
                    bm25_rank=rank,
                    dense_rank=0,
                    rrf_score=0.0,
                    page_number=chunk.page_number,
                    sheet_name=chunk.sheet_name,
                    cell_range=chunk.cell_range,
                    content_hash=chunk.content_hash,
                    parser_name=chunk.parser_name,
                    parser_version=chunk.parser_version,
                )
            )

        return SearchResponse(
            query=query,
            retrieval_mode=retrieval_mode,
            results=results,
            corpus_sha256=corpus_sha256,
            latency_ms=latencies,
        )

    # Dense 或 Hybrid：先检查索引是否存在，再校验 manifest
    if not validate_index_exists(idx_dir):
        raise index_missing("索引未构建，请先调用 POST /index 构建索引")

    _validate_manifest_or_raise(
        idx_dir, workspace_id, owner_user_id,
        corpus_sha256, chunk_ids_corpus_order,
        expected_file_ids, expected_roles,
    )

    # 加载 provider
    provider = _make_provider(model_cache_dir)
    provider_meta = provider.metadata()

    corpus_embeddings, loaded_ids, idx_meta = load_dense_index(
        index_dir=idx_dir,
        corpus_sha256=corpus_sha256,
        expected_chunk_ids=chunk_ids_corpus_order,
        expected_model_revision=provider_meta.get("model_revision", MODEL_REVISION),
        expected_dimension=512,
        expected_model_repo_id=provider_meta.get("model_repo_id", MODEL_REPO_ID),
        expected_chunking_version="1.0.0",
        expected_provider_meta=provider_meta,
    )

    def encode_query_fn(q: str):
        try:
            return provider.encode_queries([q])[0]
        except EmbeddingError as e:
            raise model_unavailable("Embedding 模型不可用，请稍后重试") from e

    id_to_idx = {cid: i for i, cid in enumerate(chunk_ids_corpus_order)}

    def dense_retrieve_fn(
        q: str, _corpus: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        q_vec = encode_query_fn(q)
        scores: list[tuple[float, int, str]] = []
        for i, chunk_dict in enumerate(_corpus):
            cid = chunk_dict["chunk_id"]
            emb_idx = id_to_idx.get(cid, i)
            if emb_idx < len(corpus_embeddings):
                sim = float(np.dot(q_vec, corpus_embeddings[emb_idx]))
                if sim > 0:
                    scores.append((sim, i, cid))
        scores.sort(key=lambda x: (-x[0], x[2]))
        results = []
        for sim_val, idx, cid_val in scores[:top_k]:
            chunk_dict = _corpus[idx]
            results.append({
                "chunk_id": chunk_dict["chunk_id"],
                "file_role": chunk_dict["file_role"],
                "file_name": chunk_dict["file_name"],
                "locator_type": chunk_dict["locator_type"],
                "page_number": chunk_dict.get("page_number"),
                "sheet_name": chunk_dict.get("sheet_name"),
                "cell_range": chunk_dict.get("cell_range"),
                "text_chunk_index": chunk_dict.get("text_chunk_index"),
                "section_title": chunk_dict.get("section_title"),
                "text": chunk_dict["text"],
                "score": round(sim_val, 6),
                "retrieval_mode": "dense",
            })
        return results

    if retrieval_mode == "dense":
        t1 = time.perf_counter()
        raw_results = dense_retrieve_fn(query, corpus_dicts, top_k)
        latencies["dense_ms"] = round((t1 - t0) * 1000, 1)

        ret_results: list[RetrievalResult] = []
        for rank, r in enumerate(raw_results, start=1):
            chunk = next(
                (c for c in corpus if c.chunk_id == r["chunk_id"]), None
            )
            if chunk is None:
                continue
            ret_results.append(
                RetrievalResult(
                    rank=rank,
                    chunk_id=r["chunk_id"],
                    file_id=chunk.file_id,
                    file_name=chunk.file_name,
                    file_role=chunk.file_role,
                    locator_type=chunk.locator_type,
                    quote=_truncate_quote(chunk.text),
                    score=r["score"],
                    bm25_rank=0,
                    dense_rank=rank,
                    rrf_score=0.0,
                    page_number=chunk.page_number,
                    sheet_name=chunk.sheet_name,
                    cell_range=chunk.cell_range,
                    content_hash=chunk.content_hash,
                    parser_name=chunk.parser_name,
                    parser_version=chunk.parser_version,
                )
            )

        return SearchResponse(
            query=query,
            retrieval_mode=retrieval_mode,
            results=ret_results,
            index_sha256=idx_meta.get("index_sha256", ""),
            corpus_sha256=corpus_sha256,
            model_revision=MODEL_REVISION,
            rrf_k=RRF_K,
            latency_ms=latencies,
        )

    # Hybrid RRF
    def bm25_retrieve_fn(
        q: str, _corpus: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        scorer = BM25Scorer(_corpus)
        scores = scorer.score(q)
        results = []
        for cid, bm_score in scores[:top_k]:
            chunk_dict = next(
                (c for c in _corpus if c["chunk_id"] == cid), None
            )
            if chunk_dict is None:
                continue
            results.append({
                "chunk_id": chunk_dict["chunk_id"],
                "file_role": chunk_dict["file_role"],
                "file_name": chunk_dict["file_name"],
                "locator_type": chunk_dict["locator_type"],
                "page_number": chunk_dict.get("page_number"),
                "sheet_name": chunk_dict.get("sheet_name"),
                "cell_range": chunk_dict.get("cell_range"),
                "text_chunk_index": chunk_dict.get("text_chunk_index"),
                "section_title": chunk_dict.get("section_title"),
                "text": chunk_dict["text"],
                "score": bm_score,
                "retrieval_mode": "bm25",
            })
        return results

    t1 = time.perf_counter()
    raw_results = hybrid_rrf_retrieve(
        query,
        corpus_dicts,
        top_k,
        bm25_retrieve_fn=bm25_retrieve_fn,
        dense_retrieve_fn=dense_retrieve_fn,
    )
    latencies["hybrid_ms"] = round((time.perf_counter() - t1) * 1000, 1)
    latencies["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    ret_results = []
    for r in raw_results:
        chunk = next(
            (c for c in corpus if c.chunk_id == r["chunk_id"]), None
        )
        if chunk is None:
            continue
        ret_results.append(
            RetrievalResult(
                rank=len(ret_results) + 1,
                chunk_id=r["chunk_id"],
                file_id=chunk.file_id,
                file_name=chunk.file_name,
                file_role=chunk.file_role,
                locator_type=chunk.locator_type,
                quote=_truncate_quote(chunk.text),
                score=r.get("rrf_score", r["score"]),
                bm25_rank=r.get("bm25_rank", 0),
                dense_rank=r.get("dense_rank", 0),
                rrf_score=r.get("rrf_score", 0.0),
                page_number=chunk.page_number,
                sheet_name=chunk.sheet_name,
                cell_range=chunk.cell_range,
                content_hash=chunk.content_hash,
                parser_name=chunk.parser_name,
                parser_version=chunk.parser_version,
            )
        )

    return SearchResponse(
        query=query,
        retrieval_mode=retrieval_mode,
        results=ret_results,
        index_sha256=idx_meta.get("index_sha256", ""),
        corpus_sha256=corpus_sha256,
        model_revision=MODEL_REVISION,
        rrf_k=RRF_K,
        latency_ms=latencies,
    )


# ── 清理 ─────────────────────────────────────────────────────────────


def cleanup_retrieval_index(workspace_id: int) -> list[tuple[Path, str]]:
    """收集需清理的索引文件路径。

    同时覆盖带版本标识的资产文件（dense_index_*.npz 等）、
    旧版固定文件名和当前版本指针（current_version.json）。
    """
    idx_dir = _index_dir(workspace_id)
    plan: list[tuple[Path, str]] = []
    for pattern in (
        "dense_index_*.npz",
        "dense_index_meta_*.json",
        "corpus_manifest_*.json",
        "current_version.json",
    ):
        for file_path in idx_dir.glob(pattern):
            if file_path.is_file():
                plan.append((file_path, f"retrieval_index:{workspace_id}/{file_path.name}"))
    return plan


# ── 辅助 ──────────────────────────────────────────────────────────────


def _truncate_quote(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"
