#!/usr/bin/env python3
"""Stage 4C-2 真实验证：工程 Verification Agent 端到端闭环。

仅在用户明确运行时使用真实 DeepSeek + 真实缓存 BGE。
不在 pytest 收集范围内（位于 scripts/，非 tests/）。

验证流程：
    1. 创建测试 App + TestClient（临时 SQLite + 隔离上传/索引目录，无默认存储污染）
    2. 注册/登录测试用户（每次运行独立用户名）
    3. 创建工程工作区，上传五份 golden 材料，understand + 确认角色
    4. 确认 Brief → 创建并执行 ReviewRun（12 Findings + 2 passed）
    5. 运行 Verification Agent（use_deepseek=true，真实 DeepSeek 一次）
    6. 查看计划与 ToolCall（真实 BGE 检索）
    7. 验证候选证据边界（Finding/Evidence 前后不变）
    8. 注入 INDEX_STALE 并展示局部 prepare + retry 链

要求：
    - 真实 DeepSeek 输出失败时不得伪造成功，报告真实错误并判定是否阻断
    - 不使用 Fake Provider
    - 不污染默认数据库和存储；finally 恢复全局配置
    - 不使用递归删除
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
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

import app.models  # noqa: F401,E402 — 注册全部模型表


ROLE_MAP = {
    "01_合成招标要求.pdf": "tender_requirement",
    "02_合成投标响应.pdf": "bid_response",
    "03_人员设备清单.xlsx": "personnel_equipment_data",
    "04_合成资质附件.pdf": "qualification_attachment",
    "05_项目澄清.md": "clarification_document",
}
PASSWORD = "VerifyPass123!"
REQUIRED_TABLES = [
    "invite_codes", "users", "auth_sessions", "workspaces", "files",
    "workspace_files", "file_profiles", "file_chunks",
    "review_runs", "review_findings", "evidences", "review_briefs",
    "review_verification_runs", "review_tool_calls",
]


def _fail(msg: str, exit_code: int = 1):
    print(f"  [FAIL] {msg}")
    sys.exit(exit_code)


def _pass(msg: str = ""):
    print(f"  [PASS]{' ' + msg if msg else ''}")


def _clear_dir_entries(directory: Path) -> None:
    """清空目录条目：逐个处理明确条目（先子目录后文件），拒绝符号链接。"""
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
    """逐文件清理本次运行创建的专属临时目录（禁止递归删除）。"""
    if not root.name.startswith("verify_4c2_"):
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


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Stage 4C-2 真实 Verification Agent 验证")
    parser.add_argument(
        "--model-cache-dir",
        default=None,
        help="模型缓存目录（默认使用 backend/data/model_cache）",
    )
    args = parser.parse_args()

    # 临时数据库 / 上传目录 / 索引目录
    tmp_db_fd, tmp_db_path = tempfile.mkstemp(suffix=".db", prefix="verify_4c2_")
    os.close(tmp_db_fd)
    tmp_db_file = Path(tmp_db_path)
    tmp_index_dir = Path(tempfile.mkdtemp(prefix="verify_4c2_idx_"))
    tmp_upload_dir = Path(tempfile.mkdtemp(prefix="verify_4c2_up_"))

    client = None
    test_engine = None
    saved_upload_dir = None
    try:
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db_path}"

        from app.core.config import settings
        from app.db.base import Base
        from app.db.session import get_db
        from sqlalchemy import create_engine, inspect
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        test_engine = create_engine(
            f"sqlite:///{tmp_db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(test_engine)
        TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

        actual_tables = set(inspect(test_engine).get_table_names())
        missing = [t for t in REQUIRED_TABLES if t not in actual_tables]
        if missing:
            print(f"  [FAIL] 临时数据库缺少表: {missing}")
            sys.exit(1)
        _pass(f"临时数据库建表完成（{len(actual_tables)} 张表，必需 {len(REQUIRED_TABLES)} 张齐全）")

        from app.main import app
        from fastapi.testclient import TestClient

        def override_get_db():
            db = TestSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        import app.services.engineering_retrieval_service as svc_mod
        svc_mod._INDEX_ROOT = tmp_index_dir / "workspaces"
        (tmp_index_dir / "workspaces").mkdir(parents=True, exist_ok=True)

        # 隔离上传目录（settings 为 frozen dataclass）
        saved_upload_dir = settings.upload_dir
        object.__setattr__(settings, "upload_dir", str(tmp_upload_dir))

        if args.model_cache_dir:
            os.environ["SENTENCE_TRANSFORMERS_HOME"] = args.model_cache_dir

        client = TestClient(app)

        for fname in ROLE_MAP:
            if not (_GOLDEN / fname).exists():
                _fail(f"golden 材料缺失: {_GOLDEN / fname}")
        _pass("golden 材料完整")
        print(f"  数据库: {tmp_db_path}")
        print(f"  上传目录: {tmp_upload_dir}")
        print(f"  索引目录: {tmp_index_dir / 'workspaces'}")

        # ── 注册/登录 ──
        from app.services.security_service import invite_code_hash, invite_code_hint
        from app.models.invite_code import InviteCode

        raw_invite = f"VERIFY-4C2-{uuid.uuid4().hex[:8].upper()}"
        db = TestSessionLocal()
        try:
            db.add(InviteCode(
                code_hash=invite_code_hash(raw_invite),
                code_hint=invite_code_hint(raw_invite),
                status="active", max_uses=100, used_count=0,
            ))
            db.commit()
        finally:
            db.close()

        csrf_resp = client.get("/api/v2/auth/csrf")
        csrf_hdr = {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name, "")}
        username = f"verify_4c2_{uuid.uuid4().hex[:8]}"
        reg = client.post("/api/v2/auth/register", headers=csrf_hdr, json={
            "username": username, "password": PASSWORD, "password_confirm": PASSWORD,
            "invite_code": raw_invite,
        })
        if reg.status_code not in (201, 409):
            _fail(f"注册失败: {reg.status_code} {reg.text}")
        client.get("/api/v2/auth/csrf")
        csrf_hdr = {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name, "")}
        login = client.post("/api/v2/auth/login", headers=csrf_hdr, json={
            "username": username, "password": PASSWORD,
        })
        if login.status_code != 200:
            _fail(f"登录失败: {login.status_code} {login.text}")
        # 登录后 CSRF cookie 已替换为会话绑定值，重新读取
        csrf_hdr = {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name, "")}
        _pass(f"用户已注册并登录（{username}）")

        # ── 工作区 + 五文件 ──
        ws = client.post("/api/v2/workspaces", headers=csrf_hdr, json={
            "name": "4C-2 真实验证工程", "workspace_type": "engineering",
        })
        if ws.status_code != 201:
            _fail(f"创建工作区失败: {ws.status_code} {ws.text}")
        ws_id = ws.json()["id"]

        file_ids: dict[int, str] = {}
        for fname, role in ROLE_MAP.items():
            content = (_GOLDEN / fname).read_bytes()
            r = client.post(
                f"/api/v2/workspaces/{ws_id}/files",
                headers=csrf_hdr,
                files={"file": (fname, io.BytesIO(content))},
            )
            if r.status_code != 201:
                _fail(f"上传 {fname} 失败: {r.status_code} {r.text}")
            fid = r.json()["file_id"]
            u = client.post(
                f"/api/v2/workspaces/{ws_id}/files/understand",
                headers=csrf_hdr, json={"file_ids": [fid]},
            )
            if u.status_code != 200:
                _fail(f"理解 {fname} 失败: {u.status_code}")
            p = client.patch(
                f"/api/v2/workspaces/{ws_id}/files/{fid}/profile",
                headers=csrf_hdr, json={"confirmed_role": role},
            )
            if p.status_code != 200:
                _fail(f"确认角色 {fname} 失败: {p.status_code}")
            file_ids[fid] = role
            print(f"  ✓ {fname} → file_id={fid} ({role})")
        _pass("5 个文件理解完成 + 角色已确认")

        # ── Brief → ReviewRun → execute ──
        brief_data = json.loads((_GOLDEN / "review_brief.json").read_text(encoding="utf-8"))
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-briefs", headers=csrf_hdr, json={
            "raw_requirements": "工程审查",
            "interpreted": brief_data["interpreted"],
            "interpreter_type": "deterministic_fixture",
        })
        if r.status_code != 201:
            _fail(f"创建 Brief 失败: {r.status_code} {r.text}")
        bid = r.json()["id"]
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-briefs/{bid}/confirm", headers=csrf_hdr)
        if r.status_code != 200:
            _fail(f"确认 Brief 失败: {r.status_code} {r.text}")

        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs", headers=csrf_hdr,
                        json={"review_brief_id": bid})
        if r.status_code != 201:
            _fail(f"创建 ReviewRun 失败: {r.status_code} {r.text}")
        run_id = r.json()["id"]
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/execute", headers=csrf_hdr)
        if r.status_code != 200:
            _fail(f"执行 ReviewRun 失败: {r.status_code} {r.text}")
        exec_data = r.json()
        print(f"  ReviewRun: {exec_data['status']}, findings={exec_data['finding_count']}, "
              f"passed={exec_data['passed_rule_ids']}")

        # 记录 Finding/Evidence 基线
        r = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/findings", headers=csrf_hdr)
        findings_before = r.json()
        r = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/evidences", headers=csrf_hdr)
        evidences_before = r.json()
        baseline = {
            "finding_ids": sorted(f["id"] for f in findings_before),
            "finding_state": {
                f["id"]: (f["status"], f["evidence_ids"]) for f in findings_before
            },
            "evidence_count": len(evidences_before),
        }

        # ── Verification Agent（真实 DeepSeek + 真实 BGE）──
        print()
        print("=" * 64)
        print("[verification] 运行 Verification Agent（use_deepseek=true）…")
        print("=" * 64)
        v0 = time.perf_counter()
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/verification-runs",
            headers=csrf_hdr,
            json={"use_deepseek": True, "max_tool_calls": 5},
        )
        wall_ms = (time.perf_counter() - v0) * 1000
        if r.status_code not in (200, 201):
            print(f"  [FAIL] Verification 调用失败: {r.status_code}")
            print(r.text[:2000])
            print("  ⚠ 真实 DeepSeek 输出失败，如实报告，判定为阻断")
            sys.exit(1)
        vdata = r.json()
        print(f"  status: {vdata['status']} (reused={vdata['reused']}, 墙钟 {wall_ms:.0f} ms)")
        print(f"  planner_type: {vdata['planner_type']}, fallback_used: {vdata['fallback_used']}")
        if vdata.get("fallback_reason"):
            print(f"  fallback_reason: {vdata['fallback_reason']}")
        print(f"  model: {vdata.get('model_provider')}/{vdata.get('model_name')}")
        print(f"  prompt_version: {vdata.get('prompt_version')}")
        print(f"  token_usage: {vdata.get('token_usage')}")
        print(f"  input_state_hash: {vdata.get('input_state_hash')}")

        # ── DeepSeek 合法规划判定（fallback 视为本项失败）──
        # 主验证断言：官方 JSON 模式参数 + finish_reason=stop + 全覆盖计划
        token_usage = vdata.get("token_usage") or {}
        completion_tokens = token_usage.get("completion_tokens") or 0
        reasoning_tokens = token_usage.get("completion_tokens_details", {}).get(
            "reasoning_tokens", 0
        ) or 0
        print(f"  模型响应：completion_tokens={completion_tokens}, "
              f"reasoning_tokens={reasoning_tokens}")

        # 判定 1：thinking=disabled 生效（reasoning 应≈0；显著大于 0 判失败）
        if reasoning_tokens > 64:
            print(f"  [FAIL] thinking=disabled 未生效：reasoning_tokens={reasoning_tokens}")
            print("  ⚠ 预期 reasoning_tokens≈0（官方 JSON 模式已禁用推理）")
            sys.exit(1)

        deepseek_ok = (
            vdata.get("planner_type") == "deepseek"
            and vdata.get("fallback_used") is False
        )
        if deepseek_ok:
            _pass("DeepSeek 合法规划：planner_type=deepseek, fallback_used=false")
            _pass("thinking=disabled 生效：reasoning_tokens≈0")
        else:
            print(f"  [FAIL] DeepSeek 合法规划验证失败：planner_type={vdata.get('planner_type')}, "
                  f"fallback_used={vdata.get('fallback_used')}")
            print(f"  ⚠ fallback_reason: {vdata.get('fallback_reason')}")
            print(f"  ⚠ token_usage: {token_usage}")
            print("  ⚠ 不得把 'API 返回 201 且 fallback 成功' 当作 DeepSeek 自主规划通过")
        decisions = vdata.get("plan", {}).get("decisions", [])
        retrieve_count = sum(1 for d in decisions if d.get("decision") == "retrieve")
        skip_count = sum(1 for d in decisions if d.get("decision") == "skip")
        print(f"  计划: retrieve={retrieve_count}, skip={skip_count}, 总数={len(decisions)}")
        if deepseek_ok:
            plan_ok = (
                retrieve_count >= 1
                and skip_count >= 1
                and len(decisions) == len(findings_before)
                and len({d.get("finding_id") for d in decisions}) == len(findings_before)
            )
            if plan_ok:
                _pass("计划：retrieve>=1 且 skip>=1，每个 Finding 恰好一次")
            else:
                print(f"  [FAIL] DeepSeek 计划不满足全覆盖/双决策要求")
                print(f"  ⚠ retrieve={retrieve_count}, skip={skip_count}, "
                      f"总数={len(decisions)}, findings={len(findings_before)}")
                sys.exit(1)
        for d in decisions:
            if d.get("decision") == "retrieve":
                print(f"    retrieve finding={d['finding_id']} [{d['issue_code']}] "
                      f"query=\"{d['query']}\" mode={d['retrieval_mode']} top_k={d['top_k']}")
            else:
                print(f"    skip    finding={d['finding_id']} [{d['issue_code']}] — {d['reason']}")
        print(f"  工具: budget={vdata['tool_budget']}, used={vdata['tool_calls_used']}, "
              f"success={vdata['success_count']}, failed={vdata['failed_count']}, "
              f"retry={vdata['retry_count']}")
        print(f"  candidates: {vdata['candidate_count']}")
        print(f"  index_sha256: {vdata.get('index_sha256', '')[:16]}…")
        print(f"  corpus_sha256: {vdata.get('corpus_sha256', '')[:16]}…")
        print(f"  latency_ms: {vdata.get('latency_ms')}")

        # ── ToolCall 详情 ──
        r = client.get(
            f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/verification-runs/"
            f"{vdata['verification_run_id']}/tool-calls",
            headers=csrf_hdr,
        )
        if r.status_code != 200:
            _fail(f"获取 ToolCall 失败: {r.status_code}")
        tool_calls = r.json()
        print(f"\n  ToolCall 记录（{len(tool_calls)} 条）:")
        retrieval_latencies: list[int] = []
        for t in tool_calls:
            print(f"    #{t['id']} {t['tool_name']} attempt={t['attempt_number']} "
                  f"status={t['status']} finding={t['review_finding_id']} "
                  f"retry_of={t['retry_of_id']} latency={t['latency_ms']}ms")
            if t["tool_name"] == "engineering_hybrid_retrieval" and t["status"] == "success":
                retrieval_latencies.append(t["latency_ms"] or 0)
                for res in (t.get("output") or {}).get("results", [])[:3]:
                    print(f"      rank={res['rank']} {res['chunk_id']} file={res['file_id']} "
                          f"role={res['file_role']} locator={res['locator_type']} "
                          f"score={res['score']} content_hash={res['content_hash'][:12]}…")

        if retrieval_latencies:
            p50 = statistics.median(retrieval_latencies)
            p95 = sorted(retrieval_latencies)[
                min(len(retrieval_latencies) - 1, int(len(retrieval_latencies) * 0.95))
            ]
            print(f"  检索延迟 P50={p50:.0f}ms P95={p95:.0f}ms "
                  f"（{len(retrieval_latencies)} 次成功检索）")
            success_rate = (
                sum(1 for t in tool_calls if t["status"] == "success") / len(tool_calls)
            ) * 100
            print(f"  工具成功率: {success_rate:.1f}%")

        # ── 候选证据边界 ──
        r = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/findings", headers=csrf_hdr)
        findings_after = r.json()
        r = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/evidences", headers=csrf_hdr)
        evidences_after = r.json()
        after_state = {
            "finding_ids": sorted(f["id"] for f in findings_after),
            "finding_state": {f["id"]: (f["status"], f["evidence_ids"]) for f in findings_after},
            "evidence_count": len(evidences_after),
        }
        if after_state == baseline:
            _pass("候选证据边界：Finding/Evidence 前后完全不变（候选不写入正式记录）")
        else:
            _fail("候选证据边界：Finding/Evidence 发生变化！")
        for t in tool_calls:
            if t["tool_name"] == "engineering_hybrid_retrieval" and t["status"] == "success":
                out = t.get("output") or {}
                if out.get("candidate_only") is True and out.get("requires_human_confirmation") is True:
                    _pass(f"工具 #{t['id']} 输出 candidate_only=true + requires_human_confirmation=true")
                else:
                    _fail(f"工具 #{t['id']} 缺少候选边界标记")

        # ── 幂等验证 ──
        # 首次运行中 prepare 已构建索引（index_sha 从空变为有值 → 新 hash → 新 run，
        # 符合"索引重建后产生新 hash"语义）。此时状态稳定：
        # 第二次运行（确定性）→ 第三次同输入应 200 + reused=true，且不重复任何调用。
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/verification-runs",
            headers=csrf_hdr,
            json={"use_deepseek": False, "max_tool_calls": 5},
        )
        if r.status_code not in (200, 201):
            _fail(f"第二次 verification 失败: {r.status_code} {r.text}")
        second_run_id = r.json().get("verification_run_id")
        print(f"  ✓ 第二次运行（确定性，索引已就绪）→ verification_run_id={second_run_id}")

        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/verification-runs",
            headers=csrf_hdr,
            json={"use_deepseek": False, "max_tool_calls": 5},
        )
        if r.status_code == 200 and r.json().get("reused") is True:
            _pass("幂等复用：相同输入返回 200 + reused=true，未创建新 run")
        else:
            _fail(f"幂等复用失败: {r.status_code} {r.text}")

        # ── 注入 INDEX_STALE 展示局部重试 ──
        print()
        print("=" * 64)
        print("[stale-injection] 修改角色 → 注入 INDEX_STALE → 展示局部重试 …")
        print("=" * 64)
        # 修改一个文件角色（tender_requirement → supplementary_attachment）
        target_fid = next(fid for fid, role in file_ids.items() if role == "tender_requirement")
        r = client.patch(
            f"/api/v2/workspaces/{ws_id}/files/{target_fid}/profile",
            headers=csrf_hdr,
            json={"confirmed_role": "supplementary_attachment"},
        )
        if r.status_code != 200:
            _fail(f"注入角色变化失败: {r.status_code}")
        # 恢复 tender_requirement（需要第二个文件？只有 1 个 tender）→ 不恢复，保持角色变化
        print(f"  ✓ file_id={target_fid} 角色改为 supplementary_attachment（corpus 变化 → STALE）")

        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/verification-runs",
            headers=csrf_hdr,
            json={"use_deepseek": False, "max_tool_calls": 5},
        )
        if r.status_code not in (200, 201):
            _fail(f"STALE 注入验证失败: {r.status_code} {r.text}")
        stale_data = r.json()
        print(f"  status: {stale_data['status']}, retry_count: {stale_data['retry_count']}")
        r = client.get(
            f"/api/v2/workspaces/{ws_id}/review-runs/{run_id}/verification-runs/"
            f"{stale_data['verification_run_id']}/tool-calls",
            headers=csrf_hdr,
        )
        stale_calls = r.json()
        for t in stale_calls:
            print(f"    #{t['id']} {t['tool_name']} attempt={t['attempt_number']} "
                  f"status={t['status']} retry_of={t['retry_of_id']} "
                  f"error={t['error_code'] or ''}")

        stale_hybrid = [t for t in stale_calls if t["tool_name"] == "engineering_hybrid_retrieval"]
        stale_prepare = [t for t in stale_calls if t["tool_name"] == "engineering_retrieval_index_prepare"]
        has_stale = any(t.get("error_code") == "ENGINEERING_RETRIEVAL_INDEX_STALE" for t in stale_hybrid)
        has_retry = any(t["attempt_number"] == 2 and t["status"] == "success" for t in stale_hybrid)
        if has_stale and stale_prepare and has_retry:
            _pass("INDEX_STALE → prepare → retry 局部重试链完整")
        else:
            print("  ⚠ STALE 重试链不完整（如实报告，判定阻断）")
            sys.exit(1)

        print()
        print("=" * 64)
        if not deepseek_ok:
            print("[FAIL] Stage 4C-2 真实验证未通过：DeepSeek 未生成合法规划（fallback 已被使用）")
            print(f"  planner_type={vdata.get('planner_type')}, fallback_reason={vdata.get('fallback_reason')}")
            sys.exit(1)
        print("[PASS] Stage 4C-2 真实验证全部通过！")
        print(f"  workspace_id: {ws_id}, review_run_id: {run_id}")
        print(f"  findings: {len(findings_before)}（12 基线）, candidates: {vdata['candidate_count']}")
        print(f"  planner_type: {vdata['planner_type']}, fallback: {vdata['fallback_used']}")
        print(f"  model: {vdata.get('model_provider')}/{vdata.get('model_name')}")
        print(f"  token_usage: {vdata.get('token_usage')}")
        print(f"  corpus_sha256: {vdata.get('corpus_sha256')}")
        print(f"  index_sha256: {vdata.get('index_sha256')}")
        print(f"  tool 调用: {vdata['tool_calls_used']}/{vdata['tool_budget']}, "
              f"success={vdata['success_count']}, failed={vdata['failed_count']}")
        if retrieval_latencies:
            print(f"  检索延迟 P50={statistics.median(retrieval_latencies):.0f}ms, "
                  f"P95={sorted(retrieval_latencies)[min(len(retrieval_latencies)-1, int(len(retrieval_latencies)*0.95))]:.0f}ms")
        print("=" * 64)
    finally:
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
        if saved_upload_dir is not None:
            object.__setattr__(settings, "upload_dir", saved_upload_dir)
        try:
            tmp_db_file.unlink(missing_ok=True)
        except OSError:
            pass
        for _tmp_dir in (tmp_index_dir, tmp_upload_dir):
            _cleanup_verify_temp_dir(_tmp_dir)


if __name__ == "__main__":
    main()
