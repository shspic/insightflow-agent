#!/usr/bin/env python3
"""Stage 4C-1 真实验证：工程工作区检索端到端闭环。

仅在用户明确运行时加载真实 BGE 模型。
不在 pytest 收集范围内（位于 scripts/，非 tests/）。

验证流程：
    1. 创建测试 App + TestClient（临时 SQLite + 隔离索引目录，无 app.db 污染）
    2. 注册/登录测试用户（每次运行独立用户名）
    3. 创建工程工作区
    4. 上传 5 个 golden 材料（multipart）
    5. 执行文件理解（understand）
    6. PATCH profile 确认工程角色
    7. 构建索引
    8. Q011/Q013/Q028 分别在 Dense 与 Hybrid RRF 下检索
    9. 幂等重建验证
    10. offline 模式检索（仅 --offline）

要求：
    - 使用真实 BGE 模型（BAAI/bge-small-zh-v1.5）
    - 支持 --model-cache-dir 和 --offline
    - 出错返回非零退出码
    - 不得通过 skip 掩盖失败
    - 无论成功或异常都清理本次创建的临时资源
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"
_GOLDEN = _REPO_ROOT / "examples" / "engineering_review_v1" / "golden_case"

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import app.models  # noqa: F401,E402  — 必须先注册全部模型表到 Base.metadata


# 5 个 golden 材料及其工程角色
GOLDEN_FILES = [
    ("01_合成招标要求.pdf", "tender_requirement"),
    ("02_合成投标响应.pdf", "bid_response"),
    ("03_人员设备清单.xlsx", "personnel_equipment_data"),
    ("04_合成资质附件.pdf", "qualification_attachment"),
    ("05_项目澄清.md", "clarification_document"),
]

# 验证检索查询（来自 retrieval_queries.json）
TEST_QUERIES = [
    ("Q011", "人员清单中项目负责人的证书编号是什么"),
    ("Q013", "设备清单中有哪些检测设备"),
    ("Q028", "人员清单中是否有人的姓名为空"),
]

# 临时数据库必须包含的表（缺失即安全失败）
REQUIRED_TABLES = [
    "invite_codes",
    "users",
    "auth_sessions",
    "workspaces",
    "files",
    "workspace_files",
    "file_profiles",
    "file_chunks",
]


def _fail(msg: str, exit_code: int = 1):
    print(f"  [FAIL] {msg}")
    sys.exit(exit_code)


def _clear_dir_entries(directory: Path) -> None:
    """清空目录条目：逐个处理明确条目（先子目录后文件），拒绝符号链接。

    不使用任何递归删除命令/函数；目录仅在自己被清空后才由调用方 rmdir。
    """
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (p.is_dir(), p.name))
    except OSError as exc:
        print(f"  ⚠ 无法枚举目录（保留）: {directory}（{exc}）")
        return
    for entry in entries:
        try:
            if entry.is_symlink():
                print(f"  ⚠ 跳过清理（符号链接）: {entry}")
                continue
            if entry.is_dir():
                _clear_dir_entries(entry)
                entry.rmdir()
            elif entry.is_file():
                entry.unlink()
        except OSError as exc:
            print(f"  ⚠ 清理失败（保留）: {entry}（{exc}）")


def _cleanup_verify_temp_dir(root: Path) -> None:
    """逐文件清理本次运行创建的专属临时目录（禁止递归删除）。

    安全约束：
    - 名称必须为固定前缀 verify_4c1_（本脚本 mkdtemp 创建）
    - 拒绝符号链接目录
    - 逐个处理目录内明确文件；仅对已经清空的明确目录调用 rmdir()
    - 清理失败只报告该隔离目录，不影响默认数据库和业务存储
    """
    if not root.name.startswith("verify_4c1_"):
        print(f"  ⚠ 跳过清理（名称不是本次专属前缀）: {root}")
        return
    try:
        if root.is_symlink() or not root.is_dir():
            print(f"  ⚠ 跳过清理（非普通目录）: {root}")
            return
        _clear_dir_entries(root)
        root.rmdir()
    except OSError as exc:
        print(f"  ⚠ 临时目录清理失败（保留）: {root}（{exc}）")


def _pass(msg: str = ""):
    label = f"  [PASS]{' ' + msg if msg else ''}"
    print(label)


def _check_field(value: Any, expected: Any, label: str, errors: list[str]):
    ok = value == expected
    mark = "✓" if ok else "✗"
    print(f"    {mark} {label}: {value!r}")
    if not ok:
        errors.append(f"{label}: 预期 {expected!r}，实际 {value!r}")
    return ok


def main():
    # Windows 控制台默认 GBK，无法输出 ✓/✗；统一强制 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Stage 4C-1 真实模型端到端验证")
    parser.add_argument(
        "--model-cache-dir",
        default=None,
        help="模型缓存目录（默认使用 backend/data/model_cache）",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="强制离线模式（HF_HUB_OFFLINE=1）",
    )
    args = parser.parse_args()

    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    errors: list[str] = []

    # ── 环境准备 ──────────────────────────────────────────────────────
    print("=" * 64)
    print("[0/6] 准备测试环境（临时数据库 + 隔离索引目录 + TestClient）…")
    print("=" * 64)

    # 创建临时 SQLite 数据库（不污染 app.db）
    tmp_db_fd, tmp_db_path = tempfile.mkstemp(suffix=".db", prefix="verify_4c1_")
    os.close(tmp_db_fd)
    tmp_db_file = Path(tmp_db_path)

    # 创建隔离索引目录（不写入 backend/storage/retrieval/workspaces）
    tmp_index_dir = Path(tempfile.mkdtemp(prefix="verify_4c1_idx_"))
    tmp_index_root = tmp_index_dir / "workspaces"

    # 创建隔离上传目录（不写入 backend/storage/uploads）
    tmp_upload_dir = Path(tempfile.mkdtemp(prefix="verify_4c1_up_"))

    client = None
    test_engine = None
    try:
        db_url = f"sqlite:///{tmp_db_path}"
        os.environ["DATABASE_URL"] = db_url

        from app.core.config import settings
        from app.db.base import Base
        from app.db.session import get_db

        # 临时替换数据库引擎
        from sqlalchemy import create_engine, inspect
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        test_engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # 完整模型注册后再建表（根因修复：先前 create_all 先于 app.models 导入）
        Base.metadata.create_all(test_engine)
        TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

        # 检查必需表真实存在，缺失立即安全失败
        actual_tables = set(inspect(test_engine).get_table_names())
        missing = [t for t in REQUIRED_TABLES if t not in actual_tables]
        if missing:
            print(f"  [FAIL] 临时数据库缺少表: {missing}")
            print(f"  实际表: {sorted(actual_tables)}")
            sys.exit(1)
        _pass(f"临时数据库建表完成（{len(actual_tables)} 张表，必需 8 张齐全）")

        # 创建 FastAPI 应用并覆盖 get_db
        from app.main import app
        from fastapi.testclient import TestClient

        def override_get_db():
            db = TestSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        # 隔离索引目录：重定向服务模块的 _INDEX_ROOT
        import app.services.engineering_retrieval_service as svc_mod
        svc_mod._INDEX_ROOT = tmp_index_root
        tmp_index_root.mkdir(parents=True, exist_ok=True)

        # 隔离上传目录：上传服务每次调用时读取 settings.upload_dir
        # （settings 为 frozen dataclass，需用 object.__setattr__ 覆写）
        object.__setattr__(settings, "upload_dir", str(tmp_upload_dir))
        print(f"  上传目录: {tmp_upload_dir}")

        # 设置模型缓存目录（LocalEmbeddingProvider 通过 cache_folder 显式使用）
        if args.model_cache_dir:
            os.environ["SENTENCE_TRANSFORMERS_HOME"] = args.model_cache_dir

        client = TestClient(app)

        # 验证 golden 材料存在
        for fname, _ in GOLDEN_FILES:
            fpath = _GOLDEN / fname
            if not fpath.exists():
                _fail(f"golden 材料缺失: {fpath}")
        _pass("golden 材料完整")
        print(f"  数据库: {tmp_db_path}")
        print(f"  索引目录: {tmp_index_root}")

        # ── 注册/登录 ─────────────────────────────────────────────────
        print()
        print("=" * 64)
        print("[1/6] 注册/登录测试用户 …")
        print("=" * 64)

        # 创建邀请码（每次运行独立，避免与历史数据冲突）
        from app.services.security_service import invite_code_hash, invite_code_hint
        from app.models.invite_code import InviteCode

        raw_invite = f"VERIFY-4C1-{uuid.uuid4().hex[:8].upper()}"
        db = TestSessionLocal()
        try:
            invite = InviteCode(
                code_hash=invite_code_hash(raw_invite),
                code_hint=invite_code_hint(raw_invite),
                status="active",
                max_uses=100,
                used_count=0,
            )
            db.add(invite)
            db.commit()
        finally:
            db.close()

        # 获取 CSRF token
        csrf_resp = client.get("/api/v2/auth/csrf")
        if csrf_resp.status_code != 200:
            _fail(f"获取 CSRF 失败: {csrf_resp.status_code}")
        csrf_header = {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name, "")}

        username = f"verify_4c1_{uuid.uuid4().hex[:8]}"
        # 注册
        reg_resp = client.post("/api/v2/auth/register", headers=csrf_header, json={
            "username": username,
            "password": "VerifyPass123!",
            "password_confirm": "VerifyPass123!",
            "invite_code": raw_invite,
        })
        if reg_resp.status_code not in (201, 409):
            _fail(f"注册失败: {reg_resp.status_code} {reg_resp.text}")

        # 重新获取 CSRF
        csrf_resp2 = client.get("/api/v2/auth/csrf")
        csrf_header2 = {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name, "")}

        # 登录
        login_resp = client.post("/api/v2/auth/login", headers=csrf_header2, json={
            "username": username,
            "password": "VerifyPass123!",
        })
        if login_resp.status_code != 200:
            _fail(f"登录失败: {login_resp.status_code} {login_resp.text}")
        _pass(f"用户已注册并登录（{username}）")

        # ── 创建工作区 ────────────────────────────────────────────────
        print()
        print("=" * 64)
        print("[2/6] 创建工程工作区 …")
        print("=" * 64)

        csrf_hdr = {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name, "")}
        ws_resp = client.post("/api/v2/workspaces", headers=csrf_hdr, json={
            "name": "验证测试工程",
            "workspace_type": "engineering",
        })
        if ws_resp.status_code != 201:
            _fail(f"创建工作区失败: {ws_resp.status_code} {ws_resp.text}")

        ws_data = ws_resp.json()
        workspace_id = ws_data["id"]
        print(f"  workspace_id: {workspace_id}")
        _check_field(ws_data["workspace_type"], "engineering", "workspace_type", errors)
        _pass("工作区创建完成")

        # ── 上传 5 个 golden 材料 ─────────────────────────────────────
        print()
        print("=" * 64)
        print("[3/6] 上传 5 个 golden 材料 …")
        print("=" * 64)

        file_ids: list[int] = []
        file_roles: dict[int, str] = {}

        for fname, role in GOLDEN_FILES:
            fpath = _GOLDEN / fname
            with open(fpath, "rb") as fh:
                content = fh.read()
            resp = client.post(
                f"/api/v2/workspaces/{workspace_id}/files",
                headers=csrf_hdr,
                files={"file": (fname, io.BytesIO(content))},
            )
            if resp.status_code != 201:
                print(f"  响应: {resp.text[:300]}")
                _fail(f"上传 {fname} 失败: {resp.status_code}")

            fid = resp.json()["file_id"]
            file_ids.append(fid)
            file_roles[fid] = role
            print(f"  ✓ {fname} → file_id={fid} ({role})")

        _check_field(len(file_ids), 5, "上传文件数", errors)
        _pass("5 个文件上传完成")

        # ── 文件理解 + 确认角色 ───────────────────────────────────────
        print()
        print("=" * 64)
        print("[4/6] 文件理解 + 确认工程角色 …")
        print("=" * 64)

        for fid in file_ids:
            # 批量理解
            resp = client.post(
                f"/api/v2/workspaces/{workspace_id}/files/understand",
                headers=csrf_hdr,
                json={"file_ids": [fid]},
            )
            if resp.status_code != 200:
                print(f"  理解响应: {resp.text[:200]}")
                _fail(f"文件 {fid} 理解失败: {resp.status_code}")

            # 确认角色
            role = file_roles[fid]
            patch_resp = client.patch(
                f"/api/v2/workspaces/{workspace_id}/files/{fid}/profile",
                headers=csrf_hdr,
                json={"confirmed_role": role},
            )
            if patch_resp.status_code != 200:
                print(f"  PATCH 响应: {patch_resp.text[:200]}")
                _fail(f"确认角色 {fid}→{role} 失败: {patch_resp.status_code}")

            print(f"  ✓ file_id={fid} 理解完成 + 角色确认为 {role}")

        # 验证 5 个 profile 已就绪
        for fid in file_ids:
            profile_resp = client.get(
                f"/api/v2/workspaces/{workspace_id}/files/{fid}/profile",
            )
            if profile_resp.status_code != 200:
                _fail(f"获取 profile {fid} 失败: {profile_resp.status_code}")
            profile_data = profile_resp.json()
            _check_field(profile_data.get("status"), "ready", f"file {fid} status", errors)

        _pass("5 个文件理解完成 + 角色已确认")

        # ── 索引状态 + 构建索引 ───────────────────────────────────────
        print()
        print("=" * 64)
        print("[5/6] 构建 Dense Index（真实 BGE）…")
        print("=" * 64)

        # 先查状态（应为 not_built 或 empty）
        status_resp = client.get(
            f"/api/v2/workspaces/{workspace_id}/engineering-retrieval/index",
        )
        if status_resp.status_code != 200:
            print(f"  响应: {status_resp.text[:300]}")
            _fail(f"查询索引状态失败: {status_resp.status_code}")
        status_data = status_resp.json()
        print(f"  初始状态: {status_data.get('status')}")
        _check_field(status_data.get("chunk_count", 0) > 0, True, "chunk_count > 0", errors)

        # 构建索引
        t0 = time.perf_counter()
        build_resp = client.post(
            f"/api/v2/workspaces/{workspace_id}/engineering-retrieval/index",
            headers=csrf_hdr,
            json={"rebuild": False},
        )
        build_time = (time.perf_counter() - t0) * 1000
        if build_resp.status_code != 200:
            print(f"  响应: {build_resp.text[:500]}")
            _fail(f"构建索引失败: {build_resp.status_code}")
        build_data = build_resp.json()
        build_status = build_data.get("status", "")
        print(f"  构建状态: {build_status}")
        print(f"  chunk_count: {build_data.get('chunk_count')}")
        print(f"  file_count: {build_data.get('file_count')}")
        print(f"  model_repo_id: {build_data.get('model_repo_id')}")
        print(f"  model_revision: {build_data.get('model_revision', '')[:8]}…")
        print(f"  corpus_sha256: {build_data.get('corpus_sha256', '')[:16]}…")
        print(f"  index_sha256: {build_data.get('index_sha256', '')[:16]}…")
        print(f"  构建耗时: {build_time:.0f} ms")

        _check_field(build_status, "built", "build status", errors)
        _pass("索引构建完成（首次构建）")

        # 读取索引 meta 文件获取 provider/dimension/dtype/normalized/device
        meta_info: dict[str, Any] = {}
        meta_path = tmp_index_root / str(workspace_id) / "dense_index_meta.json"
        meta_paths = sorted(tmp_index_root.glob(f"{workspace_id}/dense_index_meta_*.json"))
        if meta_paths:
            meta_path = meta_paths[-1]
        if meta_path.exists():
            try:
                meta_info = json.loads(meta_path.read_text("utf-8"))
                print(f"  provider: {meta_info.get('provider')}")
                print(f"  embedding_dimension: {meta_info.get('embedding_dimension')}")
                print(f"  dtype: {meta_info.get('dtype')}")
                print(f"  normalize_embeddings: {meta_info.get('normalize_embeddings')}")
                print(f"  device: {meta_info.get('device')}")
            except (json.JSONDecodeError, OSError):
                print("  ⚠ 无法读取索引 meta 文件")

        # ── 检索验证 ──────────────────────────────────────────────────
        print()
        print("=" * 64)
        print("[6/6] 检索测试（Q011, Q013, Q028 — Dense + Hybrid RRF）+ 幂等重建 …")
        print("=" * 64)

        search_summary: dict[str, dict[str, Any]] = {}
        for qid, qtext in TEST_QUERIES:
            print(f"\n  {qid}: \"{qtext}\"")
            search_summary[qid] = {}
            for mode in ("dense", "hybrid_rrf"):
                t1 = time.perf_counter()
                search_resp = client.post(
                    f"/api/v2/workspaces/{workspace_id}/engineering-retrieval/search",
                    headers=csrf_hdr,
                    json={"query": qtext, "top_k": 5, "retrieval_mode": mode},
                )
                search_ms = (time.perf_counter() - t1) * 1000
                if search_resp.status_code != 200:
                    print(f"  响应: {search_resp.text[:300]}")
                    _fail(f"检索 {qid} [{mode}] 失败: {search_resp.status_code}")

                search_data = search_resp.json()
                result_count = len(search_data.get("results", []))
                resp_latency = search_data.get("latency_ms", {})
                print(f"  [{mode}] 结果数: {result_count}, 请求耗时: {search_ms:.0f} ms, "
                      f"服务端耗时: {resp_latency}")

                for r in search_data.get("results", [])[:5]:
                    locator_detail = ""
                    if r.get("locator_type") == "pdf_page":
                        locator_detail = f"page={r.get('page_number')}"
                    elif r.get("locator_type") == "spreadsheet_cell":
                        locator_detail = (f"sheet={r.get('sheet_name')} "
                                          f"range={r.get('cell_range')}")
                    elif r.get("locator_type") == "text_chunk":
                        locator_detail = f"index={r.get('text_chunk_index')}"
                    print(
                        f"    rank={r['rank']} {r['chunk_id']} file_id={r['file_id']} "
                        f"role={r['file_role']} locator={r['locator_type']}({locator_detail}) "
                        f"score={r.get('score', 0):.6f} "
                        f"(bm25_r={r.get('bm25_rank', 0)}, dense_r={r.get('dense_rank', 0)})"
                    )
                    quote_preview = r.get("quote", "")[:60]
                    print(f"        \"{quote_preview}…\"")
                    _check_field(len(r.get("quote", "")) > 0, True, f"{qid} has quote", errors)

                _check_field(result_count > 0, True, f"{qid} [{mode}] has results", errors)
                search_summary[qid][mode] = {
                    "count": result_count,
                    "latency_ms": search_ms,
                    "results": [
                        {
                            "rank": r["rank"],
                            "file_id": r.get("file_id"),
                            "file_role": r.get("file_role"),
                            "locator_type": r.get("locator_type"),
                            "page_number": r.get("page_number"),
                            "sheet_name": r.get("sheet_name"),
                            "cell_range": r.get("cell_range"),
                            "score": r.get("score"),
                            "bm25_rank": r.get("bm25_rank"),
                            "dense_rank": r.get("dense_rank"),
                            "quote": r.get("quote", ""),
                        }
                        for r in search_data.get("results", [])[:5]
                    ],
                }

        # ── 幂等重建 ──────────────────────────────────────────────────
        print()
        print("--- 幂等重建验证 ---")

        # 不带 rebuild 的构建应返回 already_built
        rebuild_resp = client.post(
            f"/api/v2/workspaces/{workspace_id}/engineering-retrieval/index",
            headers=csrf_hdr,
            json={"rebuild": False},
        )
        rebuild_data = rebuild_resp.json()
        print(f"  无 rebuild: {rebuild_data.get('status')}")
        _check_field(
            rebuild_data.get("status") in ("already_built", "built"),
            True,
            "already_built",
            errors,
        )

        # 带 rebuild=True 的构建应返回 built
        force_resp = client.post(
            f"/api/v2/workspaces/{workspace_id}/engineering-retrieval/index",
            headers=csrf_hdr,
            json={"rebuild": True},
        )
        force_data = force_resp.json()
        print(f"  rebuild=True: {force_data.get('status')}")
        _check_field(force_data.get("status"), "built", "rebuild status", errors)

        _pass("幂等重建验证通过")

        # ── offline 模式检索 ──────────────────────────────────────────
        if args.offline:
            print()
            print("--- offline 模式检索 ---")
            search_resp2 = client.post(
                f"/api/v2/workspaces/{workspace_id}/engineering-retrieval/search",
                headers=csrf_hdr,
                json={"query": "轨道交通资质要求", "top_k": 3, "retrieval_mode": "hybrid_rrf"},
            )
            if search_resp2.status_code != 200:
                _fail(f"offline 检索失败: {search_resp2.status_code} {search_resp2.text[:300]}")
            print(f"  offline 检索状态: {search_resp2.status_code}, "
                  f"结果数: {len(search_resp2.json().get('results', []))}")
            _pass("offline 检索通过")

        # ── 总结 ──────────────────────────────────────────────────────
        print()
        print("=" * 64)
        if errors:
            print(f"[FAIL] {len(errors)} 个验证失败:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        else:
            print("[PASS] Stage 4C-1 真实端到端验证全部通过！")
            print(f"  workspace_id: {workspace_id}")
            print(f"  files: 5, chunks: {build_data.get('chunk_count', '?')}")
            print(f"  model: {build_data.get('model_repo_id', '?')} @ "
                  f"{build_data.get('model_revision', '?')[:12]}")
            print(f"  provider: {meta_info.get('provider', '?')}, "
                  f"dimension: {meta_info.get('embedding_dimension', '?')}, "
                  f"dtype: {meta_info.get('dtype', '?')}, "
                  f"normalized: {meta_info.get('normalize_embeddings', '?')}, "
                  f"device: {meta_info.get('device', '?')}")
            print(f"  corpus_sha256: {build_data.get('corpus_sha256', '?')}")
            print(f"  index_sha256: {build_data.get('index_sha256', '?')}")
            print(f"  查询模式: Q011/Q013/Q028 × Dense/Hybrid_RRF")
            for qid, modes in search_summary.items():
                for mode, info in modes.items():
                    top = info["results"][0] if info["results"] else {}
                    print(
                        f"  {qid} [{mode}]: count={info['count']} "
                        f"top_rank={top.get('rank')} top_file_id={top.get('file_id')} "
                        f"top_score={top.get('score')} latency={info['latency_ms']:.0f}ms"
                    )
            print(f"  build time: {build_time:.0f} ms")
        print("=" * 64)
    finally:
        # 无论成功或异常：关闭连接、清理本次创建的临时资源
        if client is not None:
            try:
                from app.main import app
                app.dependency_overrides.clear()
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
        if test_engine is not None:
            try:
                test_engine.dispose()
            except Exception:
                pass
        try:
            tmp_db_file.unlink(missing_ok=True)
        except OSError:
            pass
        # 逐文件清理本次 mkdtemp 创建的专属临时目录（禁止递归删除）
        for _tmp_dir in (tmp_index_dir, tmp_upload_dir):
            _cleanup_verify_temp_dir(_tmp_dir)


if __name__ == "__main__":
    main()
