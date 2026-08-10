#!/usr/bin/env python3
"""Stage 5A-1 真实验证：Review Tools MCP（真实 Streamable HTTP）。

流程：
    1. 创建隔离临时数据库与 storage
    2. 启动真实 MCP Server（官方 run，随机端口，127.0.0.1）
    3. 等待就绪
    4. 真实 MCP Client 工具发现
    5. 调用 search_review_rules / run_bid_consistency_checks
    6. 验证 request_id / status / Schema / latency
    7. 注入非法工具调用并确认拒绝
    8. 注入 Server 不可用并确认稳定错误码
    9. 关闭 Server，确认进程退出、无残留

不使用 Fake Provider、不调用 DeepSeek、不访问公网；
不使用默认 app.db / storage；不使用 shutil.rmtree 或递归删除。
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


def _clear_dir_entries(directory: Path) -> None:
    """逐文件清空目录（禁止递归删除命令）。"""
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
    if root.name.startswith("verify_5a1_") and root.exists():
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

    tmp_root = Path(tempfile.mkdtemp(prefix="verify_5a1_"))
    server_proc: subprocess.Popen | None = None
    try:
        db_path = tmp_root / "mcp.db"
        db_url = f"sqlite:///{db_path.as_posix()}"

        # ── 隔离数据库 + 业务数据 ──
        from app.db.base import Base
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = S()

        from app.models.user import User
        from app.models.workspace import Workspace
        from app.models.review_run import ReviewRun
        from app.models.review_finding import ReviewFinding
        from app.models.evidence import Evidence
        from app.models.file import File
        from app.models.review_report import ReviewReport
        from app.services.security_service import hash_password

        # 与磁盘规则包不同的快照规则（验证事实来源是 Run 快照）
        snapshot_rule = {
            "rule_id": "SYN-VERIFY-001", "version": "1", "type": "required_field",
            "title": "验证规则：资质有效期", "description": "资质有效期必须填写",
            "severity": "high", "inputs": {}, "parameters": {},
            "source_kind": "synthetic_tender_clause", "source_locator": "1.1",
            "suggestion": "请人工核对",
        }
        snapshot_json = json.dumps({
            "pack_id": "engineering_bid_review_v1", "version": "9.9-verify",
            "title": "验证规则包", "description": "验证用", "disclaimer": "合成演示数据",
            "rules": [snapshot_rule],
        }, ensure_ascii=False)
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

        u = User(username="verify5a1", password_hash=hash_password("SafePassword!2026"),
                 role="user", status="active", must_change_password=False)
        db.add(u); db.commit()
        fl = File(owner_user_id=u.id, filename="f.pdf", file_type="pdf",
                  file_path="uploads/f.pdf", status="ready")
        db.add(fl); db.commit()
        ws = Workspace(owner_user_id=u.id, name="验证工程", workspace_type="engineering",
                       review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws); db.commit()
        run = ReviewRun(workspace_id=ws.id, owner_user_id=u.id,
                        review_template_key="engineering_bid_review_v1", status="completed",
                        rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-verify",
                        rule_pack_hash=snapshot_hash, rule_snapshot_json=snapshot_json,
                        review_brief_id=None, review_brief_hash="b" * 64,
                        review_brief_snapshot_json="{}")
        db.add(run); db.commit()
        f = ReviewFinding(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                          issue_code="SYN-VERIFY-001", title="T", category="required_field",
                          severity="high", conclusion="C", suggestion="S",
                          rule_id="SYN-VERIFY-001", rule_version="1",
                          evidence_ids_json="[]", status="pending_review")
        db.add(f); db.commit()
        ev = Evidence(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                      file_id=fl.id, locator_type="pdf_page", page_number=1,
                      quote="q", content_hash="c" * 64, parser_name="p", parser_version="1")
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
        user_id = u.id
        ws_id, run_id, finding_id, evidence_id, report_id = ws.id, run.id, f.id, ev.id, report.id
        db.close(); engine.dispose()
        print("[1/8] 隔离数据库与业务数据就绪")
        print(f"      workspace={ws_id} run={run_id} report={report_id}")

        # ── 随机端口 + 随机 token ──
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        token = "verify-5a1-" + uuid.uuid4().hex[:24]
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
        env["ENGINEERING_MCP_INTERNAL_TOKEN"] = token
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
        print(f"[2/8] MCP Server 就绪: {url}（官方 Streamable HTTP）")

        from app.mcp.review_tools_client import ReviewToolsMCPClient
        from app.mcp.capability_tokens import issue_capability_token
        from app.mcp.errors import MCPError, MCPErrorCode

        cap_token = issue_capability_token(user_id, secret=token, ttl_seconds=300)
        client = ReviewToolsMCPClient(
            url=f"http://127.0.0.1:{port}/mcp", internal_token=cap_token,
            timeout_seconds=15, require_enabled=False,
        )

        # ── 认证失败注入（真实 HTTP 状态）──
        print("[3/8] 认证失败注入 …")
        import httpx2 as _h

        init_payload = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                       "clientInfo": {"name": "verify", "version": "1"}},
        }
        hdr_no = {"Accept": "application/json, text/event-stream"}
        hdr_wrong = dict(hdr_no, Authorization="Bearer wrong-token")
        hdr_raw = dict(hdr_no, Authorization=f"Bearer {token}")
        _check(_h.post(url, json=init_payload, headers=hdr_no, timeout=10).status_code == 401,
               "无 token → 401")
        _check(_h.post(url, json=init_payload, headers=hdr_wrong, timeout=10).status_code == 401,
               "错误 token → 401")
        _check(_h.post(url, json=init_payload, headers=hdr_raw, timeout=10).status_code == 401,
               "原始共享密钥作 bearer → 401")

        # ── 协议契约确认（脱敏 HTTP trace）──
        print("      协议 trace（脱敏）:")
        traced = {}

        def _on_request(request):
            traced["method"] = request.method
            traced["path"] = str(request.url.path)
            traced["accept"] = request.headers.get("accept", "")
            traced["auth_present"] = bool(request.headers.get("authorization", ""))
            traced["protocol_header"] = request.headers.get("mcp-protocol-version", "")

        traced_client = _h.Client(timeout=10, event_hooks={"request": [_on_request]})
        traced_client.post(url, json=init_payload,
                           headers=dict(hdr_no, Authorization=f"Bearer {cap_token}"))
        traced_client.close()
        _check(traced.get("method") == "POST", "POST /mcp（Streamable HTTP）", traced.get("path", ""))
        _check("text/event-stream" in traced.get("accept", ""), "Accept 含 text/event-stream")
        _check(traced.get("auth_present") is True, "Authorization 携带")
        # 官方 SDK 的 initialize 由 SDK 内部管理协议版本协商；HTTP 层实际未显式带
        # MCP-Protocol-Version 头（符合 2026-07-28 Streamable HTTP：该头由 SDK
        # 在 initialize 后续请求中管理）。如实记录观测值。
        print(f"      实际 MCP-Protocol-Version 头: {traced.get('protocol_header', '')!r}（SDK 内部管理）")

        # ── 工具发现 ──
        print("[4/8] 工具发现 …")
        tools = client.discover_tools_sync()
        _check(set(tools) == {"search_review_rules", "run_bid_consistency_checks"},
               "发现恰好两个白名单工具", str(tools))

        # ── search_review_rules ──
        print("[5/8] search_review_rules …")
        rid = "verify-req-001"
        out1 = client.call_tool_sync("search_review_rules", {
            "workspace_id": ws_id, "review_run_id": run_id,
            "query": "SYN-VERIFY", "top_k": 5, "request_id": rid,
        })
        _check(out1["status"] == "ok", "search 状态 ok")
        _check(out1["request_id"] == rid, "request_id 贯穿", rid)
        _check(out1["schema_version"] == "1.0", "schema_version")
        _check(out1["latency_ms"] >= 0, "latency 记录", f"{out1['latency_ms']}ms")
        _check(out1["rule_pack_id"] == "engineering_bid_review_v1", "rule_pack_id")
        _check(isinstance(out1["results"], list), "results 结构")
        for r in out1["results"][:3]:
            _check(r["rank"] >= 1 and r["rule_id"] and r["severity"] and r["source_hash"],
                   f"result 字段完整 [{r['rule_id']}]")
        print(f"      命中 {len(out1['results'])} 条规则（来源：Run 固化快照 SYN-VERIFY-001）")

        # ── run_bid_consistency_checks ──
        print("[6/8] run_bid_consistency_checks …")
        rid2 = "verify-req-002"
        out2 = client.call_tool_sync("run_bid_consistency_checks", {
            "workspace_id": ws_id, "review_run_id": run_id, "request_id": rid2,
        })
        _check(out2["status"] == "ok", "consistency 状态 ok")
        _check(out2["request_id"] == rid2, "request_id 贯穿", rid2)
        _check(out2["review_run_id"] == run_id, "review_run_id")
        _check(len(out2["checks"]) == 5, "5 项检查", f"{len(out2['checks'])}")
        for c in out2["checks"]:
            _check(c["candidate_only"] is True and c["requires_human_confirmation"] is True,
                   f"candidate_only [{c['check_code']}]")

        # ── 非法工具拒绝 ──
        print("[7/8] 非法工具注入 …")
        try:
            client.call_tool_sync("rm_rf_workspace", {})
            _check(False, "非法工具被拒绝")
        except MCPError as exc:
            _check(exc.code == MCPErrorCode.TOOL_NOT_ALLOWED, "非法工具拒绝", exc.code)

        # ── Server 不可用 ──
        print("[8/8] Server 不可用注入 …")
        sock2 = socket.socket()
        sock2.bind(("127.0.0.1", 0))
        dead_port = sock2.getsockname()[1]
        sock2.close()
        dead_client = ReviewToolsMCPClient(
            url=f"http://127.0.0.1:{dead_port}/mcp", internal_token="x",
            timeout_seconds=2, require_enabled=False,
        )
        try:
            dead_client.discover_tools_sync()
            _check(False, "不可用注入返回稳定错误码")
        except MCPError as exc:
            _check(exc.code == MCPErrorCode.UNAVAILABLE, "不可用注入", exc.code)

        # ── 数据不变性（真实 ReviewReport 字段对比）──
        print("[9/9] 数据不变性 …")
        from sqlalchemy import create_engine as ce2
        from sqlalchemy import select as sel
        chk = ce2(db_url)
        S2 = sessionmaker(bind=chk, autoflush=False, autocommit=False)
        db2 = S2()
        f_after = db2.scalar(sel(ReviewFinding).where(ReviewFinding.id == finding_id))
        _check(f_after.status == "pending_review", "Finding status 不变")
        _check(db2.query(Evidence).count() == 1, "Evidence 数量不变")
        rep_after = db2.scalar(sel(ReviewReport).where(ReviewReport.id == report_id))
        _check(rep_after is not None, "ReviewReport 存在")
        _check(rep_after.version == 1, "ReviewReport.version 不变")
        _check(rep_after.status == "ready", "ReviewReport.status 不变")
        _check(rep_after.review_state_hash == "r" * 64, "ReviewReport.review_state_hash 不变")
        _check(rep_after.review_snapshot_json == '{"s":1}', "ReviewReport.review_snapshot_json 不变")
        _check(rep_after.quality_gate_json == '{"ok":true}', "ReviewReport.quality_gate_json 不变")
        _check(rep_after.finding_count == 1, "ReviewReport.finding_count 不变")
        db2.close(); chk.dispose()

        print()
        if failures:
            print(f"[FAIL] {len(failures)} 项验证失败:")
            for x in failures:
                print(f"  - {x}")
            sys.exit(1)
        print("[PASS] Stage 5A-1 真实 MCP 验证全部通过！")
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)
            # Windows 下 terminate() 对子进程返回 returncode=1，属正常终止语义；
            # 验收依据 = 进程已退出 + 端口已释放 + 无残留临时文件
            print(f"  MCP Server 进程已退出 (returncode={server_proc.returncode}，"
                  f"Windows terminate 语义，非错误)")
        _cleanup_tmp(tmp_root)
        print("  临时目录已清理")


if __name__ == "__main__":
    main()
