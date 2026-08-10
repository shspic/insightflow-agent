"""V3 阶段 4B：持久化 Dense Index。

使用 NPZ（allow_pickle=False）+ JSON metadata 存储 Corpus embeddings。
校验 corpus SHA、chunk 数量/顺序、embedding 维度、模型 revision 等。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


class DenseIndexError(Exception):
    """索引构建、加载或校验失败。"""


# 版本标识：uuid4().hex，即 32 位小写十六进制
_VERSION_PATTERN = re.compile(r"[0-9a-f]{32}\Z")


def build_dense_index(
    embeddings: np.ndarray,
    chunk_ids: list[str],
    corpus_sha256: str,
    provider_meta: dict[str, Any],
    output_dir: Path,
    chunking_version: str = "1.0.0",
) -> dict[str, Any]:
    """构建持久化 Dense Index。

    生成两个文件：
    - dense_index.npz：embeddings + chunk_ids
    - dense_index_meta.json：元数据

    embeddings 必须有 (n_chunks, dim) 形状，dtype float32。
    返回构建元数据（含 index SHA-256、构建耗时等）。
    """
    t0 = time.perf_counter()

    if embeddings.ndim != 2:
        raise DenseIndexError(f"embeddings 必须为 2D，实际 {embeddings.ndim}D")
    if embeddings.dtype != np.float32:
        raise DenseIndexError(f"embeddings dtype 必须为 float32，实际 {embeddings.dtype}")
    if len(embeddings) != len(chunk_ids):
        raise DenseIndexError(
            f"embedding 行数 ({len(embeddings)}) 与 chunk_ids ({len(chunk_ids)}) 不匹配"
        )
    if np.isnan(embeddings).any():
        raise DenseIndexError("embeddings 包含 NaN")
    if np.isinf(embeddings).any():
        raise DenseIndexError("embeddings 包含 Inf")

    # 校验归一化（所有向量 L2 norm ≈ 1.0，容差 1e-4）
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise DenseIndexError(
            f"embeddings 未归一化：norm 范围 [{norms.min():.6f}, {norms.max():.6f}]"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    npz_path = output_dir / "dense_index.npz"
    meta_path = output_dir / "dense_index_meta.json"

    # 写入 NPZ（仅 float32 embeddings，chunk_ids 放在 JSON 中以确保 allow_pickle=False 兼容）
    np.savez_compressed(npz_path, embeddings=embeddings)

    # 计算 NPZ 文件 SHA-256
    npz_sha = _file_sha256(npz_path)

    meta: dict[str, Any] = {
        "corpus_sha256": corpus_sha256,
        "model_repo_id": provider_meta.get("model_repo_id", "unknown"),
        "model_revision": provider_meta.get("model_revision", "unknown"),
        "embedding_dimension": embeddings.shape[1],
        "chunk_count": len(chunk_ids),
        "chunk_ids": list(chunk_ids),
        "normalize_embeddings": provider_meta.get("normalize_embeddings", True),
        "query_instruction": provider_meta.get("query_instruction", ""),
        "chunking_version": chunking_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "index_sha256": npz_sha,
        "dtype": str(embeddings.dtype),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    build_time_ms = (time.perf_counter() - t0) * 1000

    return {
        "npz_path": str(npz_path),
        "meta_path": str(meta_path),
        "index_sha256": npz_sha,
        "build_time_ms": round(build_time_ms, 1),
        "chunk_count": len(chunk_ids),
        "embedding_dimension": embeddings.shape[1],
    }


def load_dense_index(
    index_dir: Path,
    corpus_sha256: str,
    expected_chunk_ids: list[str],
    expected_model_revision: str,
    expected_dimension: int | None = None,
    *,
    expected_model_repo_id: str | None = None,
    expected_chunking_version: str | None = None,
    expected_provider_meta: dict[str, Any] | None = None,
) -> tuple[np.ndarray, list[str], dict[str, Any]]:
    """加载并校验 Dense Index（完整契约版）。

    返回 (embeddings, chunk_ids, metadata)。

    校验项（全部失败均抛出 DenseIndexError，不静默重建）：
    1.  NPZ 文件存在且可用 allow_pickle=False 加载（上下文管理器关闭）
    2.  JSON metadata 存在
    3.  corpus_sha256 一致
    4.  model_repo_id 一致
    5.  model_revision 一致
    6.  normalize_embeddings == True
    7.  query_instruction 一致
    8.  chunking_version 一致
    9.  chunk 数量一致
    10. chunk_ids 顺序一致
    11. embedding_dimension metadata 与数组一致
    12. embeddings.dtype == float32
    13. 二维 shape
    14. 第二维等于 metadata 和 expected dimension
    15. 无 NaN
    16. 无 Inf
    17. 每行 L2 norm ≈ 1.0（容差 1e-4）
    18. NPZ 文件 SHA-256 与 metadata 记录一致（防篡改）

    任一条件不满足：抛出 DenseIndexError，提示用户使用 --rebuild-index。
    """
    assets = _resolve_active_assets(index_dir)
    if assets is None:
        raise DenseIndexError(
            f"索引文件不存在或快照不一致: {index_dir}，请使用 --rebuild-index 重新构建"
        )
    npz_path = assets["npz"]
    meta_path = assets["meta"]

    # 加载 metadata
    meta = json.loads(meta_path.read_text("utf-8"))

    # === metadata 层校验 ===

    # 1. corpus SHA
    if meta.get("corpus_sha256") != corpus_sha256:
        raise DenseIndexError(
            f"corpus SHA 不一致！索引: {meta.get('corpus_sha256', '?')[:16]}..., "
            f"当前: {corpus_sha256[:16]}...，请使用 --rebuild-index 重新构建"
        )

    # 2. model_repo_id（可通过 expected_model_repo_id 或 expected_provider_meta 提供）
    if expected_model_repo_id or expected_provider_meta:
        expected_repo = expected_model_repo_id or expected_provider_meta.get("model_repo_id", "")
        stored_repo = meta.get("model_repo_id", "")
        if stored_repo != expected_repo:
            raise DenseIndexError(
                f"模型 repo_id 不一致！索引: {stored_repo}, 当前: {expected_repo}，"
                f"请使用 --rebuild-index 重新构建"
            )

    # 3. model_revision
    stored_rev = meta.get("model_revision", "")
    if stored_rev != expected_model_revision:
        raise DenseIndexError(
            f"模型 revision 不一致！索引: {stored_rev}, 当前: {expected_model_revision}，"
            f"请使用 --rebuild-index 重新构建"
        )

    # 4. normalize_embeddings
    if expected_provider_meta:
        expected_norm = expected_provider_meta.get("normalize_embeddings", True)
        stored_norm = meta.get("normalize_embeddings", True)
        if stored_norm != expected_norm:
            raise DenseIndexError(
                f"normalize_embeddings 不一致！索引: {stored_norm}, 当前: {expected_norm}，"
                f"请使用 --rebuild-index 重新构建"
            )

    # 5. query_instruction
    if expected_provider_meta:
        expected_qi = expected_provider_meta.get("query_instruction", "")
        stored_qi = meta.get("query_instruction", "")
        if stored_qi != expected_qi:
            raise DenseIndexError(
                f"query_instruction 不一致！请使用 --rebuild-index 重新构建"
            )

    # 6. chunking_version
    if expected_chunking_version:
        stored_cv = meta.get("chunking_version", "")
        if stored_cv != expected_chunking_version:
            raise DenseIndexError(
                f"chunking_version 不一致！索引: {stored_cv}, 当前: {expected_chunking_version}，"
                f"请使用 --rebuild-index 重新构建"
            )

    # 7. chunk 数量
    stored_count = meta.get("chunk_count")
    if stored_count != len(expected_chunk_ids):
        raise DenseIndexError(
            f"chunk 数量不一致！索引: {stored_count}, 当前: {len(expected_chunk_ids)}，"
            f"请使用 --rebuild-index 重新构建"
        )

    # 8. embedding_dimension（metadata 层）
    stored_dim = meta.get("embedding_dimension")
    if expected_dimension is not None and stored_dim != expected_dimension:
        raise DenseIndexError(
            f"embedding 维度不一致！索引: {stored_dim}, 期望: {expected_dimension}，"
            f"请使用 --rebuild-index 重新构建"
        )

    # 9. dtype（metadata 层）
    stored_dtype = meta.get("dtype", "")
    if stored_dtype != "float32":
        raise DenseIndexError(
            f"索引 dtype 非 float32！实际: {stored_dtype}，请使用 --rebuild-index 重新构建"
        )

    # === NPZ 加载（allow_pickle=False，上下文管理器） ===
    try:
        with np.load(npz_path, allow_pickle=False) as data:
            embeddings = data["embeddings"].copy()
    except Exception as e:
        raise DenseIndexError(f"NPZ 加载失败: {e}，请使用 --rebuild-index 重新构建") from e

    # === 嵌入向量层校验 ===

    # 10. dtype == float32
    if embeddings.dtype != np.float32:
        raise DenseIndexError(
            f"索引 embeddings dtype 非 float32！实际: {embeddings.dtype}，"
            f"请使用 --rebuild-index 重新构建"
        )

    # 11. 二维 shape
    if embeddings.ndim != 2:
        raise DenseIndexError(
            f"索引 embeddings 为 {embeddings.ndim}D，期望 2D，请使用 --rebuild-index 重新构建"
        )
    if len(embeddings) != len(expected_chunk_ids):
        raise DenseIndexError(
            f"索引 embeddings 行数 ({len(embeddings)}) 与当前 chunk ({len(expected_chunk_ids)}) 不匹配，"
            f"请使用 --rebuild-index 重新构建"
        )

    # 12. 第二维等于 metadata dimension
    if stored_dim is not None and embeddings.shape[1] != stored_dim:
        raise DenseIndexError(
            f"索引 embeddings 第二维 ({embeddings.shape[1]}) 与 metadata ({stored_dim}) 不一致，"
            f"请使用 --rebuild-index 重新构建"
        )

    # 13. chunk_ids 顺序
    loaded_ids = meta.get("chunk_ids", [])
    if not loaded_ids:
        raise DenseIndexError("索引 metadata 中缺少 chunk_ids，请使用 --rebuild-index 重新构建")
    if loaded_ids != expected_chunk_ids:
        raise DenseIndexError(
            "索引 chunk_ids 顺序与当前语料不一致，请使用 --rebuild-index 重新构建"
        )

    # 14. 无 NaN
    if np.isnan(embeddings).any():
        raise DenseIndexError("索引 embeddings 包含 NaN，请使用 --rebuild-index 重新构建")

    # 15. 无 Inf
    if np.isinf(embeddings).any():
        raise DenseIndexError("索引 embeddings 包含 Inf，请使用 --rebuild-index 重新构建")

    # 16. L2 norm ≈ 1.0
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise DenseIndexError(
            f"索引 embeddings 未归一化：norm 范围 [{norms.min():.6f}, {norms.max():.6f}]，"
            f"请使用 --rebuild-index 重新构建"
        )

    # 17. NPZ 文件未篡改
    actual_npz_sha = _file_sha256(npz_path)
    if actual_npz_sha != meta.get("index_sha256", ""):
        raise DenseIndexError(
            "NPZ 文件 SHA-256 与 metadata 记录不一致（可能被篡改），请使用 --rebuild-index 重新构建"
        )

    return embeddings, loaded_ids, meta


def validate_index_exists(index_dir: Path) -> bool:
    """检查索引文件是否存在（不做内容校验）。

    同时兼容两种布局：
    - 指针布局（current_version.json 指向带版本标识的三个资产文件）
    - 旧版固定文件名布局（dense_index.npz + dense_index_meta.json）
    """
    assets = _resolve_active_assets(index_dir)
    return assets is not None and assets["npz"].exists() and assets["meta"].exists()


def _safe_asset_path(index_dir: Path, name: str) -> Path | None:
    """校验资产文件名安全，返回 index_dir 内的普通文件路径，否则 None。

    拒绝（任一条件命中即返回 None，不读取任何内容）：
    - 非字符串或空字符串
    - 绝对路径
    - 含 `..` 的路径
    - 带子目录的路径（Path(name).name != name）
    - 符号链接
    - 非普通文件（目录等）
    - resolve 后父目录不等于 index_dir 的文件（防目录越界）
    """
    if not isinstance(name, str) or not name:
        return None
    p = Path(name)
    if p.is_absolute():
        return None
    if ".." in p.parts:
        return None
    if p.name != name:
        return None
    full = index_dir / name
    try:
        if full.is_symlink():
            return None
        if not full.is_file():
            return None
        if full.resolve().parent != index_dir.resolve():
            return None
    except OSError:
        return None
    return full


def _resolve_active_assets(index_dir: Path) -> dict[str, Path] | None:
    """解析当前生效的索引资产路径（npz/meta/manifest）。

    优先读取 current_version.json 指针；指针缺失时回退到旧版固定文件名。

    指针模式严格校验：
    - version 必须是 32 位小写十六进制（uuid4().hex 格式）
    - 三个文件名必须精确等于 dense_index_{version}.npz /
      dense_index_meta_{version}.json / corpus_manifest_{version}.json
    - 每个文件必须是索引目录内的普通非符号链接文件（见 _safe_asset_path）
    - 三个资产文件必须同时存在，缺任一文件都视为快照不一致（返回 None），
      避免"新 NPZ 搭配旧 metadata/manifest"等混合状态被加载

    旧版布局同样验证文件是索引目录内的普通非符号链接文件；
    manifest 允许缺失（由调用方单独处理）。
    """
    pointer = index_dir / "current_version.json"
    if pointer.exists():
        try:
            data = json.loads(pointer.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        version = data.get("version")
        if not isinstance(version, str) or _VERSION_PATTERN.fullmatch(version) is None:
            return None
        expected = {
            "npz": f"dense_index_{version}.npz",
            "meta": f"dense_index_meta_{version}.json",
            "manifest": f"corpus_manifest_{version}.json",
        }
        if (
            data.get("npz") != expected["npz"]
            or data.get("meta") != expected["meta"]
            or data.get("manifest") != expected["manifest"]
        ):
            return None
        npz = _safe_asset_path(index_dir, expected["npz"])
        meta = _safe_asset_path(index_dir, expected["meta"])
        manifest = _safe_asset_path(index_dir, expected["manifest"])
        if npz is None or meta is None or manifest is None:
            return None
        return {"npz": npz, "meta": meta, "manifest": manifest}

    # 旧版固定文件名布局：同样验证普通非符号链接文件
    npz = _safe_asset_path(index_dir, "dense_index.npz")
    meta = _safe_asset_path(index_dir, "dense_index_meta.json")
    if npz is None or meta is None:
        return None
    manifest_name = "corpus_manifest.json"
    manifest = index_dir / manifest_name
    if manifest.exists() and _safe_asset_path(index_dir, manifest_name) is None:
        return None  # manifest 存在但是符号链接/目录/越界
    return {"npz": npz, "meta": meta, "manifest": manifest}


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
