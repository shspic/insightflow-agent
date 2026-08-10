#!/usr/bin/env python3
"""Stage 5A-2 真实验证：Verification Agent 接入 MCP。

流程：
    1. 隔离 SQLite + 隔离 storage
    2. 随机端口启动真实 MCP Server（官方 Streamable HTTP）
    3. 创建真实用户/engineering workspace/ReviewRun/Finding/Evidence
    4. 通过完整 service 入口创建 VerificationRun（deterministic planner）
    5. MCP enabled；capability token 使用当前认证用户
    6. 发现并调用两个真实 MCP 工具；ToolCall 持久化
    7. plan_json 出现 mcp_context
    8. MCP 调用数与 retrieval budget 分离
    9. Finding/Evidence/ReviewReport 不变
    10. 重复调用验证 reused=true
    11. 停止 MCP Server；确认进程退出、端口释放、无残留

说明：
- MCP Server/Client 为真实 Streamable HTTP（mcp 2.0.0）
- planner 为 deterministic
- 未调用 DeepSeek；未加载真实 BGE
- 不得把 Fake/Mock 结果描述为真实模型结果
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import app.models  # noqa: F401,E402

SNAPSHOT_RULE = {
    "rule_id": "SYN-VERIFY-001", "version": "1", "type": "required_field",
    "title": "验证规则：资质有效期", "description": "资质有效期必须填写",
    "severity": "high", "inputs": {}, "parameters": {},
    "source_kind": "synthetic_tender_clause", "source_locator": "1.1",
    "suggestion": "请人工核对",
}


def _clear_dir_entries(directory: Path) -> None:
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (p.is_dir(), p.name))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                _clear_dir_entries(entry)
                entry.rmdir()
            elif entry.is_file():
                entry.unlink()
        except OSError:
            pass


def _cleanup_tmp(root: Path) -> None:
    if root.name.startswith("verify_5a2_") and root.exists():
        _clear_dir_entries(root)
        try:
            root.rmdir()
        except OSError:
            pass


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []

    def _check(ok: bool, label: str, detail: str = ""):
        print(f"  {'✓' if ok else '✗'} {label}{' — ' + detail if detail else ''}")
        if not ok:
            failures.append(label)

    tmp_root = Path(tempfile.mkdtemp(prefix="verify_5a2_"))
    server_proc: subprocess.Popen | None = None
    port = None
    try:
        db_path = tmp_root / "mcp.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        upload_dir = tmp_root / "uploads"
        upload_dir.mkdir(parents=True)

        from app.core.config import settings
        from app.db.base import Base
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker

        object.__setattr__(settings, "upload_dir", str(upload_dir))
        engine = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = S()

        from app.models.user import User
        from app.models.workspace import Workspace
        from app.models.workspace_file import WorkspaceFile
        from app.models.file_profile import FileProfile
        from app.models.review_run import ReviewRun
        from app.models.review_finding import ReviewFinding
        from app.models.evidence import Evidence
        from app.models.file import File
        from app.models.review_report import ReviewReport
        from app.models.review_tool_call import ReviewToolCall
        from app.services.security_service import hash_password

        u = User(username="verify5a2", password_hash=hash_password("SafePassword!2026"),
                 role="user", status="active", must_change_password=False)
        db.add(u); db.commit()
        real_md = upload_dir / "f.md"
        real_md.write_text("资质有效期必须填写", encoding="utf-8")
        fl = File(owner_user_id=u.id, filename="f.md", file_type="markdown",
                  file_path=str(real_md), status="ready")
        db.add(fl); db.commit()
        ws = Workspace(owner_user_id=u.id, name="验证工程", workspace_type="engineering",
                       review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws); db.commit()
        wf = WorkspaceFile(workspace_id=ws.id, file_id=fl.id,
                           user_confirmed_role="tender_requirement")
        db.add(wf); db.commit()
        prof = FileProfile(workspace_id=ws.id, file_id=fl.id, owner_user_id=u.id,
                           profile_version=1, status="ready",
                           confirmed_role="tender_requirement",
                           suggested_role="tender_requirement",
                           file_category="document", language="zh",
                           title="招标要求", summary="合成招标要求",
                           confidence=0.9, parser_name="test", parser_version="1")
        db.add(prof); db.commit()
        snap = json.dumps({
            "pack_id": "engineering_bid_review_v1", "version": "9.9-verify",
            "title": "验证规则包", "description": "验证用", "disclaimer": "合成演示数据",
            "rules": [SNAPSHOT_RULE],
        }, ensure_ascii=False)
        run = ReviewRun(workspace_id=ws.id, owner_user_id=u.id,
                        review_template_key="engineering_bid_review_v1", status="completed",
                        rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-verify",
                        rule_pack_hash=hashlib.sha256(snap.encode()).hexdigest(),
                        rule_snapshot_json=snap, review_brief_id=None,
                        review_brief_hash="b" * 64, review_brief_snapshot_json="{}")
        db.add(run); db.commit()
        f = ReviewFinding(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                          issue_code="SYN-VERIFY-001", title="资质有效期", category="required_field",
                          severity="high", conclusion="资质有效期未填写", suggestion="请核对",
                          rule_id="SYN-VERIFY-001", rule_version="1",
                          evidence_ids_json="[]", status="pending_review")
        db.add(f); db.commit()
        ev = Evidence(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                      file_id=fl.id, locator_type="text_chunk", chunk_id=1,
                      quote="资质有效期必须填写", content_hash="c" * 64,
                      parser_name="p", parser_version="1")
        db.add(ev); db.commit()
        report = ReviewReport(
            workspace_id=ws.id, owner_user_id=u.id, review_run_id=run.id,
            version=1, status="ready", review_state_hash="r" * 64,
            review_snapshot_json='{"s":1}', quality_gate_json='{"ok":true}',
            warning_count=0, finding_count=1, high_count=1, medium_count=0, low_count=0,
            confirmed_count=0, rejected_count=0, modified_count=0, resolved_count=0,
            pending_review_count=1, generator_name="verify", generator_version="1",
        )
        db.add(report); db.commit()
        user_id, ws_id, run_id, finding_id, report_id = u.id, ws.id, run.id, f.id, report.id
        db.close(); engine.dispose()
        print("[1/10] 隔离数据库与业务数据就绪")
        print(f"      workspace={ws_id} run={run_id} report={report_id}")

        # ── 随机端口 + 签名密钥 ──
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        secret = "verify-5a2-" + uuid.uuid4().hex[:16]
        out_file = tmp_root / "server.log"

        # ── 启动真实 MCP Server ──
        server_code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(_BACKEND)!r})\n"
            f"os.environ['DATABASE_URL'] = {db_url!r}\n"
            "os.environ['LLM_ENABLED'] = 'false'\n"
            "import app.models\n"
            "from app.mcp.review_tools_server import run_review_tools_server\n"
            f"run_review_tools_server(host='127.0.0.1', port={port}, streamable_http_path='/mcp')\n"
        )
        env = dict(os.environ)
        env["ENGINEERING_MCP_INTERNAL_TOKEN"] = secret
        env["ENGINEERING_MCP_ENABLED"] = "true"
        env["DATABASE_URL"] = db_url

        with open(out_file, "wb") as fout:
            server_proc = subprocess.Popen(
                [sys.executable, "-c", server_code], env=env, cwd=_BACKEND,
                stdout=fout, stderr=subprocess.STDOUT,
            )
            ready = False
            for _ in range(80):
                if server_proc.poll() is not None:
                    break
                try:
                    sck = socket.create_connection(("127.0.0.1", port), timeout=1)
                    sck.close()
                    ready = True
                    break
                except Exception:
                    time.sleep(0.25)
            if not ready:
                log = open(out_file, encoding="utf-8", errors="replace").read()[:1500]
                print("  [FAIL] MCP Server 未就绪")
                print(log)
                sys.exit(1)
        url = f"http://127.0.0.1:{port}/mcp"
        print(f"[2/10] MCP Server 就绪: {url}（真实 Streamable HTTP）")

        # ── 配置 MCP enabled + capability token（当前认证用户）──
        object.__setattr__(settings, "engineering_mcp_enabled", True)
        object.__setattr__(settings, "engineering_mcp_url", url)
        object.__setattr__(settings, "engineering_mcp_internal_token", secret)
        print("[3/10] MCP enabled + capability token（user_id=%d）" % user_id)

        # ── 先建好检索索引（使幂等验证时索引状态稳定）──
        from app.services.engineering_retrieval_service import rebuild_index
        from app.retrieval.embedding import FakeEmbeddingProvider
        import app.services.engineering_retrieval_service as svc_mod

        svc_mod._INDEX_ROOT = tmp_root / "retrieval_ws"
        (tmp_root / "retrieval_ws").mkdir(parents=True)
        svc_mod.LocalEmbeddingProvider = lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42)
        rebuild_index(S(), ws_id, user_id)
        print("      检索索引已构建（Fake Embedding，仅用于幂等稳定性）")

        # ── 创建 VerificationRun（deterministic planner，完整 service 入口）──
        from app.services.engineering_verification_service import run_verification

        db = S()
        result, reused = run_verification(
            db, workspace_id=ws_id, owner_user_id=user_id, review_run_id=run_id,
            use_deepseek=False, max_tool_calls=5, actor_user_id=user_id,
        )
        print(f"[4/10] VerificationRun: status={result['status']} reused={reused} "
              f"mcp_count={result['mcp_tool_call_count']}")
        _check(reused is False, "首次运行新建 VerificationRun")
        _check(result["status"] == "completed", "VerificationRun completed")
        _check(result["mcp_tool_call_count"] == 2, "两个真实 MCP 工具调用",
               str(result["mcp_tool_call_count"]))
        _check(result["planner_type"] == "deterministic", "deterministic planner")
        _check(result["mcp_enabled"] is True, "mcp_enabled 记录")
        _check(result["mcp_retry_count"] == 0, "首次无重试")

        # ── plan_json.mcp_context ──
        plan = result["plan"]
        _check("mcp_context" in plan, "plan_json 含 mcp_context")
        ctx = plan.get("mcp_context", {})
        _check("run_bid_consistency_checks" in ctx.get("results", {}),
               "consistency 结果写入 mcp_context")
        _check("search_review_rules" in ctx.get("results", {}),
               "rules 结果写入 mcp_context")
        _check(ctx.get("results", {}).get("run_bid_consistency_checks", {}).get("status") == "ok",
               "consistency status ok")
        _check(ctx.get("results", {}).get("search_review_rules", {}).get("status") == "ok",
               "rules status ok")

        # ── ToolCall 持久化与审计 ──
        from sqlalchemy import select as _sel
        from app.models.review_tool_call import ReviewToolCall as _RTC

        calls = list(db.scalars(_sel(_RTC).where(
            _RTC.verification_run_id == result["verification_run_id"])).all())
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        _check(len(mcp_calls) == 2, "MCP ToolCall 持久化 2 条", str(len(mcp_calls)))
        _check(all(c.status == "success" for c in mcp_calls), "MCP ToolCall 全部成功")
        _check(all(c.attempt_number == 1 for c in mcp_calls), "attempt=1")
        _check(all(c.retry_of_id is None for c in mcp_calls), "无重试链")
        # input 不含 token/secret
        for c in mcp_calls:
            _check(secret not in (c.input_json or "") and secret not in (c.output_json or ""),
                   f"ToolCall {c.tool_name} 不含 token/secret")

        # ── 预算分离 ──
        _check(result["retrieval_budget"] == 5, "retrieval budget=5")
        _check(result["mcp_tool_call_count"] == 2, "mcp 计数 2")
        _check(result["total_tool_call_count"] == result["mcp_tool_call_count"] + result["retrieval_tool_call_count"],
               "total = mcp + retrieval")

        # ── Finding/Evidence/Report 不变 ──
        db2 = S()
        f_after = db2.get(ReviewFinding, finding_id)
        _check(f_after.status == "pending_review", "Finding status 不变")
        _check(db2.query(Evidence).count() == 1, "Evidence 数量不变")
        rep_after = db2.get(ReviewReport, report_id)
        _check(rep_after.version == 1 and rep_after.review_state_hash == "r" * 64,
               "ReviewReport 关键字段不变")
        _check(rep_after.review_snapshot_json == '{"s":1}' and rep_after.quality_gate_json == '{"ok":true}',
               "ReviewReport 快照不变")

        # ── 幂等 ──
        result2, reused2 = run_verification(
            db2, workspace_id=ws_id, owner_user_id=user_id, review_run_id=run_id,
            use_deepseek=False, max_tool_calls=5, actor_user_id=user_id,
        )
        _check(reused2 is True, "重复调用 reused=true")
        _check(result2["verification_run_id"] == result["verification_run_id"],
               "复用同一 VerificationRun")
        db2.close()

        print()
        if failures:
            print(f"[FAIL] {len(failures)} 项验证失败:")
            for x in failures:
                print(f"  - {x}")
            sys.exit(1)
        print("[PASS] Stage 5A-2 真实 MCP 集成验证全部通过！")
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)
            # Windows terminate 语义：returncode=1 属正常；验收 = 进程退出 + 端口释放
            print(f"  MCP Server 进程已退出 (returncode={server_proc.returncode}，"
                  f"Windows terminate 语义)")
        if port is not None:
            released = False
            for _ in range(20):
                try:
                    sck = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                    sck.close()
                    time.sleep(0.5)
                except OSError:
                    released = True
                    break
            if released:
                print("  ✓ 端口已释放")
            else:
                print("  [FAIL] 端口仍被监听")
                failures.append("port_not_released")
        _cleanup_tmp(tmp_root)
        print("  ✓ 临时文件已清理")


if __name__ == "__main__":
    main()
