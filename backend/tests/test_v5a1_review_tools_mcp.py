"""阶段 5A-1：Review Tools MCP 专项测试（补修后）。

普通 pytest 完全离线：
- 不调用 DeepSeek / 不加载真实 BGE / 不访问公网
- 隔离 SQLite（文件临时库，MCP Server 子进程共用）
- pytest 临时目录；不写默认 app.db/uploads/reports/retrieval
- 真实 Streamable HTTP MCP 调用（子进程起 Server，随 fixture 关闭）
- 调用者身份：短期签名 capability token（HMAC，subject=user_id）
- 规则事实来源：ReviewRun 固化规则快照（不读磁盘最新规则文件）
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.mcp.capability_tokens import issue_capability_token
from app.mcp.errors import MCPError, MCPErrorCode
from app.mcp.review_tools_client import ReviewToolsMCPClient
from app.mcp.review_tools_server import (
    ALLOWED_MCP_TOOL_NAMES,
    _run_bid_consistency_checks,
    _run_search_review_rules,
    build_review_tools_mcp_server,
    run_review_tools_server,
)
from app.mcp.schemas import RunBidConsistencyChecksInput, SearchReviewRulesInput
from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_run import ReviewRun
from app.models.user import User
from app.models.workspace import Workspace
from app.services.review_rule_service import RuleLoadError
from app.services.security_service import hash_password

BACKEND_DIR = Path(__file__).resolve().parents[1]

# 与磁盘规则包不同的测试快照规则（证明事实来源是 Run 快照）
SNAPSHOT_RULE_A = {
    "rule_id": "SYN-TEST-001", "version": "1", "type": "required_field",
    "title": "测试规则：资质有效期", "description": "资质有效期必须填写并附证据",
    "severity": "high", "inputs": {}, "parameters": {},
    "source_kind": "synthetic_tender_clause", "source_locator": "1.1",
    "suggestion": "请人工核对",
}
SNAPSHOT_RULE_B = {
    "rule_id": "SYN-TEST-B", "version": "1", "type": "required_field",
    "title": "测试规则：人员证书", "description": "人员证书编号必须填写",
    "severity": "medium", "inputs": {}, "parameters": {},
    "source_kind": "synthetic_tender_clause", "source_locator": "1.2",
    "suggestion": "请人工核对",
}


def _snapshot_json(rule: dict, version: str) -> str:
    return json.dumps({
        "pack_id": "engineering_bid_review_v1", "version": version,
        "title": "测试规则包", "description": "测试用", "disclaimer": "合成演示数据",
        "rules": [rule],
    }, ensure_ascii=False)


def _snapshot_hash(snapshot: str) -> str:
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()


def _build_db(db_url: str):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()

    # 两个正常用户
    ua = User(username="mcp_user_a", password_hash=hash_password("SafePassword!2026"),
              role="user", status="active", must_change_password=False)
    db.add(ua); db.commit()
    ub = User(username="mcp_user_b", password_hash=hash_password("SafePassword!2026"),
              role="user", status="active", must_change_password=False)
    db.add(ub); db.commit()

    fl = File(owner_user_id=ua.id, filename="f.pdf", file_type="pdf",
              file_path="uploads/f.pdf", status="ready")
    db.add(fl); db.commit()

    # 用户 A 的 workspace + run（快照含 SYN-TEST-001）
    ws_a = Workspace(owner_user_id=ua.id, name="工程A", workspace_type="engineering",
                     review_template_key="engineering_bid_review_v1", status="active")
    db.add(ws_a); db.commit()
    snap_a = _snapshot_json(SNAPSHOT_RULE_A, "9.9-test-a")
    run_a = ReviewRun(workspace_id=ws_a.id, owner_user_id=ua.id,
                      review_template_key="engineering_bid_review_v1", status="completed",
                      rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-test-a",
                      rule_pack_hash=_snapshot_hash(snap_a), rule_snapshot_json=snap_a,
                      review_brief_id=None, review_brief_hash="b" * 64,
                      review_brief_snapshot_json="{}")
    db.add(run_a); db.commit()
    f_a = ReviewFinding(review_run_id=run_a.id, workspace_id=ws_a.id, owner_user_id=ua.id,
                        issue_code="SYN-TEST-001", title="T", category="required_field",
                        severity="high", conclusion="C", suggestion="S",
                        rule_id="SYN-TEST-001", rule_version="1",
                        evidence_ids_json="[]", status="pending_review")
    db.add(f_a); db.commit()
    ev = Evidence(review_run_id=run_a.id, workspace_id=ws_a.id, owner_user_id=ua.id,
                  file_id=fl.id, locator_type="pdf_page", page_number=1,
                  quote="q", content_hash="c" * 64, parser_name="p", parser_version="1")
    db.add(ev); db.commit()

    # 用户 B 的 workspace + run（快照含 SYN-TEST-B）
    ws_b = Workspace(owner_user_id=ub.id, name="工程B", workspace_type="engineering",
                     review_template_key="engineering_bid_review_v1", status="active")
    db.add(ws_b); db.commit()
    snap_b = _snapshot_json(SNAPSHOT_RULE_B, "9.9-test-b")
    run_b = ReviewRun(workspace_id=ws_b.id, owner_user_id=ub.id,
                      review_template_key="engineering_bid_review_v1", status="completed",
                      rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-test-b",
                      rule_pack_hash=_snapshot_hash(snap_b), rule_snapshot_json=snap_b,
                      review_brief_id=None, review_brief_hash="c" * 64,
                      review_brief_snapshot_json="{}")
    db.add(run_b); db.commit()

    # 真实 ReviewReport 记录（用于不变性验证）
    report = ReviewReport(
        workspace_id=ws_a.id, owner_user_id=ua.id, review_run_id=run_a.id,
        version=1, status="ready", review_state_hash="r" * 64,
        review_snapshot_json='{"s":1}', quality_gate_json='{"ok":true}',
        warning_count=0, finding_count=1, high_count=1, medium_count=0, low_count=0,
        confirmed_count=0, rejected_count=0, modified_count=0, resolved_count=0,
        pending_review_count=1, generator_name="test", generator_version="1",
    )
    db.add(report); db.commit()

    data = {
        "user_a": ua.id, "user_b": ub.id,
        "workspace_a": ws_a.id, "run_a": run_a.id, "finding_a": f_a.id,
        "workspace_b": ws_b.id, "run_b": run_b.id,
        "evidence_id": ev.id, "report_id": report.id,
    }
    db.close()
    engine.dispose()
    return data


@pytest.fixture(scope="module")
def mcp_env(tmp_path_factory):
    """模块级：临时文件 DB + 真实 MCP Server 子进程 + 签名密钥。"""
    tmp_root = tmp_path_factory.mktemp("v5a1_mcp")
    db_path = tmp_root / "mcp.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    data = _build_db(db_url)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    secret = "v5a1-signing-secret-" + uuid.uuid4().hex[:16]
    out_file = tmp_root / "server.log"

    server_code = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(BACKEND_DIR)!r})\n"
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
        proc = subprocess.Popen(
            [sys.executable, "-c", server_code], env=env, cwd=BACKEND_DIR,
            stdout=fout, stderr=subprocess.STDOUT,
        )
        ok = False
        for _ in range(80):
            if proc.poll() is not None:
                break
            try:
                sck = socket.create_connection(("127.0.0.1", port), timeout=1)
                sck.close()
                ok = True
                break
            except Exception:
                time.sleep(0.25)
        if not ok:
            log = open(out_file, encoding="utf-8", errors="replace").read()[:2000]
            proc.terminate()
            pytest.fail(f"MCP Server 未就绪: {log}")

    url = f"http://127.0.0.1:{port}/mcp"
    yield {"url": url, "secret": secret, "data": data, "proc": proc, "out_file": out_file,
           "db_url": db_url}

    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _cap_token(mcp_env, user_id: int) -> str:
    return issue_capability_token(user_id, secret=mcp_env["secret"])


def _client(mcp_env, user_id: int, **kw) -> ReviewToolsMCPClient:
    return ReviewToolsMCPClient(
        url=mcp_env["url"], internal_token=_cap_token(mcp_env, user_id),
        timeout_seconds=10, require_enabled=False, **kw,
    )


def _open_db(mcp_env):
    engine = create_engine(mcp_env["db_url"], connect_args={"check_same_thread": False})
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return S()


def _search_args(mcp_env, workspace_id=None, run_id=None, query="SYN-TEST",
                 top_k=3, request_id="req-x"):
    d = mcp_env["data"]
    return {
        "workspace_id": workspace_id if workspace_id is not None else d["workspace_a"],
        "review_run_id": run_id if run_id is not None else d["run_a"],
        "query": query, "top_k": top_k, "request_id": request_id,
    }


def _checks_args(mcp_env, workspace_id=None, run_id=None, request_id="req-y"):
    d = mcp_env["data"]
    return {
        "workspace_id": workspace_id if workspace_id is not None else d["workspace_a"],
        "review_run_id": run_id if run_id is not None else d["run_a"],
        "request_id": request_id,
    }


# ── 发现与注册 ──────────────────────────────────────────────────────


class TestDiscovery:
    def test_server_registers_exactly_two_tools(self):
        import asyncio

        server = build_review_tools_mcp_server()

        async def _list():
            tools = await server.list_tools()
            return sorted(t.name for t in tools)

        names = asyncio.run(_list())
        assert set(names) == set(ALLOWED_MCP_TOOL_NAMES)
        assert len(names) == 2

    def test_client_discovery_whitelist(self, mcp_env):
        tools = _client(mcp_env, mcp_env["data"]["user_a"]).discover_tools_sync()
        assert tools == sorted(ALLOWED_MCP_TOOL_NAMES)
        assert len(tools) == 2

    def test_non_whitelist_tool_rejected(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("not_allowed_tool", {})
        assert exc.value.code == MCPErrorCode.TOOL_NOT_ALLOWED


# ── 正常调用 ────────────────────────────────────────────────────────


class TestNormalCalls:
    def test_search_review_rules_normal(self, mcp_env):
        """正常调用：结果来自 Run 快照（SYN-TEST-001）。"""
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        out = client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        assert out["status"] == "ok"
        assert out["rule_pack_version"] == "9.9-test-a"  # 快照版本，非磁盘
        assert any(r["rule_id"] == "SYN-TEST-001" for r in out["results"])

    def test_run_bid_consistency_checks_normal(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        out = client.call_tool_sync("run_bid_consistency_checks", _checks_args(mcp_env))
        assert out["status"] == "ok"
        assert out["review_run_id"] == mcp_env["data"]["run_a"]
        assert len(out["checks"]) == 5
        for c in out["checks"]:
            assert c["candidate_only"] is True
            assert c["requires_human_confirmation"] is True

    def test_request_id_passthrough(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        rid = "req-123456"
        out = client.call_tool_sync("search_review_rules", _search_args(mcp_env, request_id=rid))
        assert out["request_id"] == rid
        out2 = client.call_tool_sync("run_bid_consistency_checks", _checks_args(mcp_env, request_id=rid))
        assert out2["request_id"] == rid

    def test_reproducible_same_input(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        a1 = client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        a2 = client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        assert [r["rule_id"] for r in a1["results"]] == [r["rule_id"] for r in a2["results"]]


# ── 调用者身份隔离 ──────────────────────────────────────────────────


class TestActorIsolation:
    def test_user_a_own_workspace_success(self, mcp_env):
        """用户 A 的签名 token 调用用户 A workspace 成功。"""
        d = mcp_env["data"]
        out = _client(mcp_env, d["user_a"]).call_tool_sync(
            "search_review_rules", _search_args(mcp_env))
        assert out["status"] == "ok"

    def test_user_a_cannot_access_user_b(self, mcp_env):
        """用户 A token 调用用户 B 的正常 workspace/run 被拒绝。"""
        d = mcp_env["data"]
        client_a = _client(mcp_env, d["user_a"])
        with pytest.raises(MCPError) as exc:
            client_a.call_tool_sync("search_review_rules",
                                    _search_args(mcp_env, workspace_id=d["workspace_b"],
                                                 run_id=d["run_b"]))
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID
        with pytest.raises(MCPError) as exc2:
            client_a.call_tool_sync("run_bid_consistency_checks",
                                    _checks_args(mcp_env, workspace_id=d["workspace_b"],
                                                 run_id=d["run_b"]))
        assert exc2.value.code == MCPErrorCode.REQUEST_INVALID

    def test_user_b_own_workspace_success(self, mcp_env):
        """用户 B token 调用用户 B workspace 成功。"""
        d = mcp_env["data"]
        out = _client(mcp_env, d["user_b"]).call_tool_sync(
            "search_review_rules",
            _search_args(mcp_env, workspace_id=d["workspace_b"], run_id=d["run_b"],
                         query="SYN-TEST-B"))
        assert out["status"] == "ok"
        assert any(r["rule_id"] == "SYN-TEST-B" for r in out["results"])

    def test_orphan_owner_run_data_integrity(self, mcp_env):
        """数据完整性：owner 与 workspace 不一致的异常 Run 被拒绝。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        snap_x = _snapshot_json(SNAPSHOT_RULE_A, "9.9-x")
        bad_run = ReviewRun(workspace_id=d["workspace_a"], owner_user_id=d["user_b"],
                            review_template_key="engineering_bid_review_v1", status="completed",
                            rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-x",
                            rule_pack_hash=_snapshot_hash(snap_x), rule_snapshot_json=snap_x,
                            review_brief_id=None, review_brief_hash="b" * 64,
                            review_brief_snapshot_json="{}")
        db.add(bad_run); db.commit()
        bad_run_id = bad_run.id
        db.close()

        client = _client(mcp_env, d["user_a"])
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules",
                                  _search_args(mcp_env, run_id=bad_run_id))
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID


# ── 401 认证失败 ────────────────────────────────────────────────────


class TestAuthFailures:
    def _post_initialize(self, mcp_env, auth_header: str | None) -> int:
        headers = {"Accept": "application/json, text/event-stream"}
        if auth_header is not None:
            headers["Authorization"] = auth_header
        resp = httpx2.post(
            mcp_env["url"],
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2026-07-28",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            headers=headers,
            timeout=10,
        )
        return resp.status_code

    def test_missing_authorization_401(self, mcp_env):
        assert self._post_initialize(mcp_env, None) == 401

    def test_wrong_token_401(self, mcp_env):
        assert self._post_initialize(mcp_env, "Bearer wrong-token-here") == 401

    def test_tampered_signature_401(self, mcp_env):
        d = mcp_env["data"]
        tok = _cap_token(mcp_env, d["user_a"])
        tampered = tok[:-8] + ("aaaa" if not tok.endswith("aaaa") else "bbbb")
        assert self._post_initialize(mcp_env, f"Bearer {tampered}") == 401

    def test_expired_token_401(self, mcp_env):
        d = mcp_env["data"]
        expired = issue_capability_token(
            d["user_a"], secret=mcp_env["secret"],
            ttl_seconds=1, now=int(time.time()) - 100,
        )
        assert self._post_initialize(mcp_env, f"Bearer {expired}") == 401

    def test_raw_secret_as_bearer_401(self, mcp_env):
        """原始共享密钥直接作为 bearer token 返回 401。"""
        assert self._post_initialize(mcp_env, f"Bearer {mcp_env['secret']}") == 401

    def test_no_token_in_response_or_log(self, mcp_env):
        """响应与日志不含 token/secret/路径/traceback。"""
        d = mcp_env["data"]
        client = _client(mcp_env, d["user_a"])
        out1 = client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        out2 = client.call_tool_sync("run_bid_consistency_checks", _checks_args(mcp_env))
        text = json.dumps([out1, out2], ensure_ascii=False)
        for forbidden in (mcp_env["secret"], "C:\\", "D:\\", "Users",
                          "Traceback", "File ", ".env", "sqlite:///"):
            assert forbidden not in text, f"泄露: {forbidden}"
        log = open(mcp_env["out_file"], encoding="utf-8", errors="replace").read()
        assert mcp_env["secret"] not in log


# ── 输入校验与隔离 ──────────────────────────────────────────────────


class TestValidationAndIsolation:
    def test_non_engineering_workspace_rejected(self, mcp_env):
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        gen = Workspace(owner_user_id=d["user_a"], name="通用",
                        workspace_type="general", status="active")
        db.add(gen); db.commit()
        gid = gen.id
        db.close()

        client = _client(mcp_env, d["user_a"])
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules", {
                "workspace_id": gid, "review_run_id": d["run_a"],
                "query": "x", "top_k": 3, "request_id": "r1",
            })
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID

    def test_cross_workspace_nesting_rejected(self, mcp_env):
        d = mcp_env["data"]
        client = _client(mcp_env, d["user_a"])
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules", {
                "workspace_id": d["workspace_a"], "review_run_id": d["run_b"],
                "query": "x", "top_k": 3, "request_id": "r3",
            })
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID

    def test_invalid_query_rejected(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules", _search_args(mcp_env, query="   "))
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID
        with pytest.raises(MCPError) as exc2:
            client.call_tool_sync("search_review_rules", _search_args(mcp_env, query="x" * 501))
        assert exc2.value.code == MCPErrorCode.REQUEST_INVALID

    def test_top_k_out_of_range(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        for bad in (0, 11):
            with pytest.raises(MCPError) as exc:
                client.call_tool_sync("search_review_rules", _search_args(mcp_env, top_k=bad))
            assert exc.value.code == MCPErrorCode.REQUEST_INVALID

    def test_extra_fields_rejected(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        args = _search_args(mcp_env)
        args["evil_extra"] = "x"
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules", args)
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID
        args2 = _checks_args(mcp_env)
        args2["owner_user_id"] = 999  # 不信任客户端传入 owner
        with pytest.raises(MCPError) as exc2:
            client.call_tool_sync("run_bid_consistency_checks", args2)
        assert exc2.value.code == MCPErrorCode.REQUEST_INVALID


# ── 错误行为 ────────────────────────────────────────────────────────


class TestErrorBehavior:
    def test_server_unavailable(self, mcp_env):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        client = ReviewToolsMCPClient(
            url=f"http://127.0.0.1:{dead_port}/mcp",
            internal_token="x", timeout_seconds=2, require_enabled=False,
        )
        with pytest.raises(MCPError) as exc:
            client.discover_tools_sync()
        assert exc.value.code == MCPErrorCode.UNAVAILABLE

    def test_request_timeout(self, mcp_env):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            client = ReviewToolsMCPClient(
                url=f"http://127.0.0.1:{port}/mcp",
                internal_token="x", timeout_seconds=1, require_enabled=False,
            )
            with pytest.raises(MCPError) as exc:
                client.discover_tools_sync()
            assert exc.value.code == MCPErrorCode.TIMEOUT
        finally:
            srv.close()

    def test_broken_response(self, mcp_env):
        import http.server
        import threading

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = b"not-json-at-all"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                self.do_POST()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            client = ReviewToolsMCPClient(
                url=f"http://127.0.0.1:{port}/mcp",
                internal_token="x", timeout_seconds=5, require_enabled=False,
            )
            with pytest.raises(MCPError) as exc:
                client.discover_tools_sync()
            assert exc.value.code in (
                MCPErrorCode.DISCOVERY_ERROR,
                MCPErrorCode.RESPONSE_INVALID,
                MCPErrorCode.UNAVAILABLE,
            )
        finally:
            srv.shutdown()
            srv.server_close()

    def test_business_error_sanitized(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules", {
                "workspace_id": 999999, "review_run_id": 1,
                "query": "x", "top_k": 3, "request_id": "r5",
            })
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID
        msg = exc.value.message
        for forbidden in ("C:\\", "D:\\", "Users", "Traceback", "File ", ".env", "sqlite"):
            assert forbidden not in msg, f"泄露: {forbidden} in {msg}"

    def test_no_local_fallback_on_failure(self, mcp_env):
        import app.mcp.review_tools_client as client_mod

        source = Path(client_mod.__file__).read_text(encoding="utf-8")
        assert "from app.services.review_rule_service import" not in source

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        client = ReviewToolsMCPClient(
            url=f"http://127.0.0.1:{dead_port}/mcp",
            internal_token="x", timeout_seconds=2, require_enabled=False,
        )
        with pytest.raises(MCPError) as exc:
            client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        assert exc.value.code == MCPErrorCode.UNAVAILABLE


# ── 数据不变性 ──────────────────────────────────────────────────────


class TestImmutability:
    def test_finding_unchanged(self, mcp_env):
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        before = db.scalar(select(ReviewFinding).where(ReviewFinding.id == d["finding_a"]))
        before_state = (before.status, before.conclusion, before.suggestion,
                        before.evidence_ids_json, before.severity)
        client = _client(mcp_env, d["user_a"])
        client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        client.call_tool_sync("run_bid_consistency_checks", _checks_args(mcp_env))
        after = db.scalar(select(ReviewFinding).where(ReviewFinding.id == d["finding_a"]))
        after_state = (after.status, after.conclusion, after.suggestion,
                       after.evidence_ids_json, after.severity)
        assert after_state == before_state
        db.close()

    def test_evidence_unchanged(self, mcp_env):
        db = _open_db(mcp_env)
        before_ids = [e.id for e in db.scalars(select(Evidence)).all()]
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        client.call_tool_sync("run_bid_consistency_checks", _checks_args(mcp_env))
        after_ids = [e.id for e in db.scalars(select(Evidence)).all()]
        assert after_ids == before_ids
        db.close()

    def test_review_report_unchanged(self, mcp_env):
        """真实 ReviewReport 关键字段在 MCP 调用前后不变。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        rep = db.scalar(select(ReviewReport).where(ReviewReport.id == d["report_id"]))
        before = (rep.id, rep.version, rep.review_state_hash,
                  rep.review_snapshot_json, rep.quality_gate_json,
                  rep.status, rep.finding_count)
        client = _client(mcp_env, d["user_a"])
        client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        client.call_tool_sync("run_bid_consistency_checks", _checks_args(mcp_env))
        rep2 = db.scalar(select(ReviewReport).where(ReviewReport.id == d["report_id"]))
        after = (rep2.id, rep2.version, rep2.review_state_hash,
                 rep2.review_snapshot_json, rep2.quality_gate_json,
                 rep2.status, rep2.finding_count)
        assert after == before
        db.close()


# ── 安全边界 ────────────────────────────────────────────────────────


class TestSecurityBoundary:
    def test_server_rejects_0_0_0_0(self):
        with pytest.raises(ValueError):
            run_review_tools_server(host="0.0.0.0", port=1)

    def test_default_bind_is_localhost(self):
        import inspect

        sig = inspect.signature(run_review_tools_server)
        assert sig.parameters["host"].default == "127.0.0.1"

    def test_internal_token_not_in_business_response(self, mcp_env):
        client = _client(mcp_env, mcp_env["data"]["user_a"])
        out1 = client.call_tool_sync("search_review_rules", _search_args(mcp_env))
        out2 = client.call_tool_sync("run_bid_consistency_checks", _checks_args(mcp_env))
        text = json.dumps([out1, out2], ensure_ascii=False)
        assert mcp_env["secret"] not in text

    def test_disabled_returns_clear_status(self, monkeypatch):
        from app.core.config import settings

        original = settings.engineering_mcp_enabled
        object.__setattr__(settings, "engineering_mcp_enabled", False)
        try:
            with pytest.raises(MCPError) as exc:
                ReviewToolsMCPClient()
            assert exc.value.code == MCPErrorCode.DISABLED
        finally:
            object.__setattr__(settings, "engineering_mcp_enabled", original)


# ── ReviewRun 规则快照（进程内 handler 测试）────────────────────────


class TestRuleSnapshot:
    """规则事实来源 = ReviewRun 固化快照，不读磁盘最新规则文件。"""

    @pytest.fixture(autouse=True)
    def _restore_run_snapshot(self, mcp_env):
        """恢复被修改测试污染的 run_a 快照/hash（模块级 DB 共享）。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == d["run_a"]))
        orig_snap, orig_hash = run.rule_snapshot_json, run.rule_pack_hash
        db.close()
        yield
        db = _open_db(mcp_env)
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == d["run_a"]))
        run.rule_snapshot_json = orig_snap
        run.rule_pack_hash = orig_hash
        db.commit()
        db.close()

    def _handler_db(self, mcp_env):
        return _open_db(mcp_env)

    def test_search_uses_run_snapshot_not_disk(self, mcp_env):
        """搜索结果必须来自 Run 快照（SYN-TEST-001 不在磁盘规则包中）。"""
        db = self._handler_db(mcp_env)
        d = mcp_env["data"]
        out = _run_search_review_rules(
            db, SearchReviewRulesInput(workspace_id=d["workspace_a"], review_run_id=d["run_a"],
                                       query="SYN-TEST", top_k=5, request_id="snap-1"),
            actor_user_id=d["user_a"],
        )
        assert out.status == "ok"
        assert out.rule_pack_version == "9.9-test-a"
        assert [r.rule_id for r in out.results] == ["SYN-TEST-001"]
        db.close()

    def test_consistency_uses_run_snapshot(self, mcp_env):
        """consistency 按 Run 快照判断 rule/severity。"""
        db = self._handler_db(mcp_env)
        d = mcp_env["data"]
        out = _run_bid_consistency_checks(
            db, RunBidConsistencyChecksInput(workspace_id=d["workspace_a"],
                                             review_run_id=d["run_a"],
                                             request_id="snap-2"),
            actor_user_id=d["user_a"],
        )
        by_code = {c.check_code: c for c in out.checks}
        assert by_code["finding_rule_exists"].status == "pass"  # SYN-TEST-001 在快照中
        assert by_code["finding_severity_matches_rule"].status == "pass"  # high==high
        db.close()

    def test_works_when_load_rule_pack_raises(self, mcp_env, monkeypatch):
        """monkeypatch load_rule_pack 抛错后，合法 Run 快照仍能工作。"""
        def _boom(*a, **kw):
            raise RuleLoadError("磁盘规则包不可用")
        monkeypatch.setattr("app.services.review_rule_service.load_rule_pack", _boom)
        db = self._handler_db(mcp_env)
        d = mcp_env["data"]
        out = _run_search_review_rules(
            db, SearchReviewRulesInput(workspace_id=d["workspace_a"], review_run_id=d["run_a"],
                                       query="SYN-TEST", top_k=5, request_id="snap-3"),
            actor_user_id=d["user_a"],
        )
        assert out.status == "ok"
        assert [r.rule_id for r in out.results] == ["SYN-TEST-001"]
        db.close()

    def test_broken_snapshot_fails_safely(self, mcp_env):
        """snapshot JSON 损坏时安全失败（稳定错误码）。"""
        db = self._handler_db(mcp_env)
        d = mcp_env["data"]
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == d["run_a"]))
        run.rule_snapshot_json = "{broken json"
        run.rule_pack_hash = "a" * 64
        db.commit()
        with pytest.raises(MCPError) as exc:
            _run_search_review_rules(
                db, SearchReviewRulesInput(workspace_id=d["workspace_a"], review_run_id=d["run_a"],
                                           query="x", top_k=3, request_id="snap-4"),
                actor_user_id=d["user_a"],
            )
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID
        db.close()

    def test_hash_mismatch_fails_safely(self, mcp_env):
        """snapshot hash 不一致时安全失败。"""
        db = self._handler_db(mcp_env)
        d = mcp_env["data"]
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == d["run_a"]))
        run.rule_pack_hash = "f" * 64
        db.commit()
        with pytest.raises(MCPError) as exc:
            _run_search_review_rules(
                db, SearchReviewRulesInput(workspace_id=d["workspace_a"], review_run_id=d["run_a"],
                                           query="x", top_k=3, request_id="snap-5"),
                actor_user_id=d["user_a"],
            )
        assert exc.value.code == MCPErrorCode.REQUEST_INVALID
        db.close()

    def test_stable_after_external_rule_change(self, mcp_env, monkeypatch):
        """外部规则包变化后，同一 Run 结果仍一致（不依赖磁盘）。"""
        import app.services.review_rule_service as rrs
        from app.schemas.review import ReviewRulePack

        calls = {"n": 0}

        def _changing(*a, **kw):
            calls["n"] += 1
            rule = dict(SNAPSHOT_RULE_A)
            rule["rule_id"] = "SYN-DISK-CHANGED"
            return ReviewRulePack.model_validate({
                "pack_id": "engineering_bid_review_v1", "version": "999",
                "title": "T", "description": "D", "disclaimer": "X", "rules": [rule],
            })

        monkeypatch.setattr(rrs, "load_rule_pack", _changing)
        db = self._handler_db(mcp_env)
        d = mcp_env["data"]
        out1 = _run_search_review_rules(
            db, SearchReviewRulesInput(workspace_id=d["workspace_a"], review_run_id=d["run_a"],
                                       query="SYN-TEST", top_k=5, request_id="snap-6"),
            actor_user_id=d["user_a"],
        )
        out2 = _run_search_review_rules(
            db, SearchReviewRulesInput(workspace_id=d["workspace_a"], review_run_id=d["run_a"],
                                       query="SYN-TEST", top_k=5, request_id="snap-7"),
            actor_user_id=d["user_a"],
        )
        assert [r.rule_id for r in out1.results] == ["SYN-TEST-001"]
        assert [r.rule_id for r in out2.results] == ["SYN-TEST-001"]
        assert calls["n"] == 0  # handler 完全不读磁盘规则
        db.close()
