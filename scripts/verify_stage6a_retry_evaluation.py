#!/usr/bin/env python3
"""Stage 6A 局部重试真实评测：真实 Streamable HTTP MCP + 受控瞬时故障注入。

场景（独立受控故障，与黄金案例评测分开）：
1. 真实 MCP Server（Streamable HTTP），通过环境变量对
   search_review_rules 注入「第一次调用失败」的受控故障；
2. 生产代码路径 _run_mcp_preflight 执行两次工具调用：
   - run_bid_consistency_checks：第一次即成功 → 不被重复执行；
   - search_review_rules：第一次 ENGINEERING_MCP_UNAVAILABLE（可重试）
     → 局部重试一次（attempt 2）→ 恢复并成功；
3. 只重试失败工具，不重复成功节点；
4. 记录 attempt_number / retry_of_id / error_code，输出
   retry_attempts / retry_successes / local_retry_success_rate；
5. 无法完成真实 transport 故障注入时脚本退出非零并如实报告。

任何硬条件失败 → 非零退出。不使用普通单元测试结果冒充真实评测。
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

ROLES = ("tender_requirement", "bid_response", "personnel_equipment_data",
         "qualification_attachment", "clarification_document")
EVAL_OUT = _REPO_ROOT / "examples/engineering_review_v1/eval_results/stage6a/retry"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    if root.name.startswith("verify_6a_retry_") and root.exists():
        _clear_dir_entries(root)
        try:
            root.rmdir()
        except OSError:
            pass


def main() -> int:
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

    tmp_root = Path(tempfile.mkdtemp(prefix="verify_6a_retry_"))
    server_proc: subprocess.Popen | None = None
    port = None
    try:
        from app.core.config import settings
        from app.db.base import Base
        from sqlalchemy import create_engine, event, select
        from sqlalchemy.orm import sessionmaker

        from app.models.user import User
        from app.models.workspace import Workspace
        from app.models.review_run import ReviewRun
        from app.models.review_finding import ReviewFinding
        from app.models.review_verification_run import ReviewVerificationRun
        from app.models.review_tool_call import ReviewToolCall
        from app.services.security_service import hash_password

        db_path = tmp_root / "retry.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        upload_dir = tmp_root / "uploads"
        upload_dir.mkdir(parents=True)
        object.__setattr__(settings, "upload_dir", str(upload_dir))
        engine = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = S()

        # ── 1. 最小工程环境（真实文件 + run + finding）──
        print("[1/4] 准备最小工程环境 …")
        u = User(username="stage6a_retry", password_hash=hash_password("SafePassword!2026"),
                 role="user", status="active", must_change_password=False)
        db.add(u); db.commit()
        ws = Workspace(owner_user_id=u.id, name="6A 重试评测", workspace_type="engineering",
                       review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws); db.commit()
        snap = json.dumps({
            "pack_id": "engineering_bid_review_v1", "version": "1.1.0",
            "title": "T", "description": "D", "disclaimer": "X",
            "rules": [{"rule_id": "SYN-NUM-001", "version": "1", "type": "numeric_threshold",
                       "title": "人员数量", "description": "人员至少 5 人", "severity": "high",
                       "inputs": {}, "parameters": {"field": "total_personnel",
                                                    "threshold": 5, "operator": "gte"},
                       "source_kind": "synthetic_tender_clause",
                       "source_locator": "1", "suggestion": "请核对"}],
        }, ensure_ascii=False)
        brief_snap = json.dumps({"id": 1, "version": 1, "content_hash": "a" * 64,
                                 "raw_requirements": "审查", "interpreted_json": "{}"})
        run = ReviewRun(workspace_id=ws.id, owner_user_id=u.id,
                        review_template_key="engineering_bid_review_v1", status="completed",
                        rule_pack_id="engineering_bid_review_v1", rule_pack_version="1.1.0",
                        rule_pack_hash=hashlib.sha256(snap.encode()).hexdigest(),
                        rule_snapshot_json=snap, review_brief_version=1,
                        review_brief_hash=hashlib.sha256(brief_snap.encode()).hexdigest(),
                        review_brief_snapshot_json=brief_snap)
        db.add(run); db.commit()
        finding = ReviewFinding(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                                issue_code="SYN-NUM-001", title="人员数量", category="numeric_threshold",
                                severity="high", conclusion="人员数量不足", suggestion="请核对",
                                rule_id="SYN-NUM-001", rule_version="1",
                                evidence_ids_json="[]", status="pending_review",
                                source_step_id="engine:SYN-NUM-001")
        db.add(finding); db.commit()
        verification = ReviewVerificationRun(
            workspace_id=ws.id, owner_user_id=u.id, review_run_id=run.id,
            status="planning", input_state_hash="a" * 64, planner_type="deterministic",
        )
        db.add(verification); db.commit()

        # ── 2. 真实 MCP Server + 故障注入 ──
        print("[2/4] 启动真实 Streamable HTTP MCP（受控故障注入）…")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        secret = "verify-6a-retry-" + uuid.uuid4().hex[:16]
        out_file = tmp_root / "server.log"
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
        env["ENGINEERING_MCP_FAULT_TOOL"] = "search_review_rules"
        env["ENGINEERING_MCP_FAULT_FIRST_N"] = "1"
        env["DATABASE_URL"] = db_url
        with open(out_file, "wb") as fout:
            server_proc = subprocess.Popen([sys.executable, "-c", server_code], env=env,
                                           cwd=_BACKEND, stdout=fout, stderr=subprocess.STDOUT)
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
                print("  [FAIL] MCP Server 未就绪（无法完成真实 transport 故障注入）")
                print(log)
                _check(False, "真实 MCP Server 启动")
                raise RuntimeError("MCP server not ready")
        url = f"http://127.0.0.1:{port}/mcp"
        object.__setattr__(settings, "engineering_mcp_enabled", True)
        object.__setattr__(settings, "engineering_mcp_url", url)
        object.__setattr__(settings, "engineering_mcp_internal_token", secret)
        print(f"  MCP 就绪: {url}（故障注入: search_review_rules 前 1 次调用失败）")

        # ── 3. 生产 preflight 路径（真实重试逻辑）──
        print("[3/4] 执行 MCP preflight（第一次失败 → 局部重试 → 恢复）…")
        from app.services.engineering_verification_service import (
            MCPErrorCode,
            _run_mcp_preflight,
        )

        warnings: list[str] = []
        mcp_context = _run_mcp_preflight(db, verification, run, u.id, warnings)
        total_calls = mcp_context.get("total_calls", 0)

        tool_calls = list(db.scalars(
            select(ReviewToolCall).where(
                ReviewToolCall.verification_run_id == verification.id,
            ).order_by(ReviewToolCall.id.asc())
        ).all())
        print(f"  preflight total_calls={total_calls}，ToolCall 记录 {len(tool_calls)} 条")
        for tc in tool_calls:
            print(f"    {tc.tool_name} attempt={tc.attempt_number} "
                  f"status={tc.status} error={tc.error_code or '-'} "
                  f"retry_of={tc.retry_of_id or '-'}")

        # 硬条件断言
        by_tool = {}
        for tc in tool_calls:
            by_tool.setdefault(tc.tool_name, []).append(tc)

        consistency = by_tool.get("run_bid_consistency_checks", [])
        _check(len(consistency) == 1, "consistency 只执行一次（成功节点不重复）",
               f"{len(consistency)} 条")
        _check(consistency and consistency[0].status == "success"
               and consistency[0].attempt_number == 1,
               "consistency attempt1 成功")

        rules = by_tool.get("search_review_rules", [])
        _check(len(rules) == 2, "rules 失败一次 + 重试一次共 2 条记录", f"{len(rules)} 条")
        if len(rules) == 2:
            a1, a2 = rules
            _check(a1.attempt_number == 1 and a1.status == "failed",
                   "rules attempt1 失败（可重试错误）", str(a1.error_code))
            _check(a1.error_code == MCPErrorCode.UNAVAILABLE,
                   "attempt1 error_code=ENGINEERING_MCP_UNAVAILABLE", str(a1.error_code))
            _check(a2.attempt_number == 2 and a2.status == "success",
                   "rules attempt2 恢复并成功")
            _check(a2.retry_of_id == a1.id,
                   "attempt2.retry_of_id 指向 attempt1", f"{a2.retry_of_id} -> {a1.id}")
        else:
            _check(False, "重试链完整（attempt1 失败 + attempt2 成功）")

        recovered = mcp_context.get("recovered_errors", [])
        _check(any(r.get("error_code") == MCPErrorCode.UNAVAILABLE
                   and r.get("attempt_number") == 1 for r in recovered),
               "recovered_errors 记录已恢复错误")
        _check(not mcp_context.get("errors"),
               "未解决 errors 为空（恢复成功不误报）")
        _check(not warnings, "preflight 无未解决 warning", str(warnings))

        retry_attempts = sum(1 for tc in tool_calls if tc.attempt_number > 1)
        retry_successes = sum(1 for tc in tool_calls
                              if tc.attempt_number > 1 and tc.status == "success")
        rate = (retry_successes / retry_attempts) if retry_attempts else None
        print(f"  retry_attempts={retry_attempts} retry_successes={retry_successes} "
              f"local_retry_success_rate={rate}")
        _check(retry_attempts == 1, "retry_attempts=1（只重试失败工具）")
        _check(retry_successes == 1, "retry_successes=1")
        _check(rate == 1.0, "local_retry_success_rate=1.0")

        # ── 4. 输出报告 ──
        print("[4/4] 输出 retry 报告 …")
        EVAL_OUT.mkdir(parents=True, exist_ok=True)
        report = {
            "scenario": "local_retry_real_mcp_fault_injection",
            "transport": "streamable_http",
            "fault": {"tool": "search_review_rules", "fail_first_n": 1,
                      "error_code": MCPErrorCode.UNAVAILABLE},
            "tool_calls": [
                {"tool_name": tc.tool_name, "attempt_number": tc.attempt_number,
                 "retry_of_id": tc.retry_of_id, "status": tc.status,
                 "error_code": tc.error_code, "latency_ms": tc.latency_ms,
                 "created_at": tc.created_at.isoformat() if tc.created_at else None}
                for tc in tool_calls
            ],
            "mcp_context": {
                "total_calls": total_calls,
                "recovered_errors": recovered,
                "errors": mcp_context.get("errors", []),
                "warnings": warnings,
            },
            "metrics": {
                "retry_attempts": retry_attempts,
                "retry_successes": retry_successes,
                "local_retry_success_rate": rate,
            },
            "python_version": sys.version.split()[0],
            "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        (EVAL_OUT / "retry_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  retry_report.json 已写入: {EVAL_OUT / 'retry_report.json'}")

        print()
        if failures:
            print(f"[FAIL] {len(failures)} 项硬条件失败:")
            for x in failures:
                print(f"  - {x}")
            return 1
        print("[PASS] Stage 6A 局部重试真实评测通过（真实 Streamable HTTP MCP 故障注入）")
        return 0
    except Exception as exc:
        print(f"[FAIL] 评测异常退出: {exc}")
        return 1
    finally:
        try:
            db.close()
        except Exception:
            pass
        try:
            engine.dispose()
        except Exception:
            pass
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)
            print(f"  MCP Server 已退出 (returncode={server_proc.returncode})")
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
            print("  ✓ 端口已释放" if released else "  [FAIL] 端口仍被监听")
        _cleanup_tmp(tmp_root)
        print("  ✓ 临时文件已清理" if not tmp_root.exists() else "  [FAIL] 临时目录残留")


if __name__ == "__main__":
    sys.exit(main())
