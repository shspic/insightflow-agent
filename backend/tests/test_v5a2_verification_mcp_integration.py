"""阶段 5A-2：Verification Agent 接入 MCP 专项测试。

普通 pytest 完全离线：
- 不调用 DeepSeek / 不加载真实 BGE / 不访问公网
- 隔离 SQLite（文件临时库，MCP Server 子进程共用）
- pytest 临时目录；不写默认 app.db/uploads/reports/retrieval
- 真实 Streamable HTTP MCP 调用（子进程起 Server）
- MCP capability token 使用 API 当前认证用户
- 检索预算（max_tool_calls）与 MCP 预算（独立 4 次）分离
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
from app.core.config import settings
from app.db.base import Base
from app.mcp.errors import MCPErrorCode
from app.mcp.review_tools_client import ReviewToolsMCPClient
from app.mcp.review_tools_server import run_review_tools_server
from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_run import ReviewRun
from app.models.review_tool_call import ReviewToolCall
from app.models.review_verification_run import ReviewVerificationRun
from app.models.file_profile import FileProfile
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.security_service import hash_password

BACKEND_DIR = Path(__file__).resolve().parents[1]

SNAPSHOT_RULE = {
    "rule_id": "SYN-TEST-001", "version": "1", "type": "required_field",
    "title": "测试规则：资质有效期", "description": "资质有效期必须填写并附证据",
    "severity": "high", "inputs": {}, "parameters": {},
    "source_kind": "synthetic_tender_clause", "source_locator": "1.1",
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


def _build_ws(db, owner: User, name: str, version: str) -> tuple[Workspace, ReviewRun]:
    ws = Workspace(owner_user_id=owner.id, name=name, workspace_type="engineering",
                   review_template_key="engineering_bid_review_v1", status="active")
    db.add(ws); db.commit()
    snap = _snapshot_json(SNAPSHOT_RULE, version)
    run = ReviewRun(workspace_id=ws.id, owner_user_id=owner.id,
                    review_template_key="engineering_bid_review_v1", status="completed",
                    rule_pack_id="engineering_bid_review_v1", rule_pack_version=version,
                    rule_pack_hash=_snapshot_hash(snap), rule_snapshot_json=snap,
                    review_brief_id=None, review_brief_hash="b" * 64,
                    review_brief_snapshot_json="{}")
    db.add(run); db.commit()
    return ws, run


def _build_db(db_url: str, upload_dir: Path):
    """upload_dir 由 fixture 提供（pytest 生命周期），不自行创建系统临时目录。"""
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()

    upload_dir.mkdir(parents=True, exist_ok=True)
    ua = User(username="v5a2_user_a", password_hash=hash_password("SafePassword!2026"),
              role="user", status="active", must_change_password=False)
    db.add(ua); db.commit()
    ub = User(username="v5a2_user_b", password_hash=hash_password("SafePassword!2026"),
              role="user", status="active", must_change_password=False)
    db.add(ub); db.commit()
    real_md = upload_dir / "f.md"
    real_md.write_text("资质有效期必须填写", encoding="utf-8")
    fl = File(owner_user_id=ua.id, filename="f.md", file_type="markdown",
              file_path=str(real_md), status="ready")
    db.add(fl); db.commit()
    ws_a, run_a = _build_ws(db, ua, "工程A", "9.9-a")
    f_a = ReviewFinding(review_run_id=run_a.id, workspace_id=ws_a.id, owner_user_id=ua.id,
                        issue_code="SYN-TEST-001", title="资质有效期", category="required_field",
                        severity="high", conclusion="资质有效期未填写", suggestion="请核对",
                        rule_id="SYN-TEST-001", rule_version="1",
                        evidence_ids_json="[]", status="pending_review")
    db.add(f_a); db.commit()
    ev = Evidence(review_run_id=run_a.id, workspace_id=ws_a.id, owner_user_id=ua.id,
                  file_id=fl.id, locator_type="pdf_page", page_number=1,
                  quote="q", content_hash="c" * 64, parser_name="p", parser_version="1")
    db.add(ev); db.commit()
    # 角色确认 + ready profile（检索 corpus 需要）
    wf = WorkspaceFile(workspace_id=ws_a.id, file_id=fl.id,
                       user_confirmed_role="tender_requirement")
    db.add(wf); db.commit()
    profile = FileProfile(workspace_id=ws_a.id, file_id=fl.id, owner_user_id=ua.id,
                          profile_version=1, status="ready",
                          confirmed_role="tender_requirement",
                          suggested_role="tender_requirement",
                          file_category="document", language="zh",
                          title="招标要求", summary="合成招标要求",
                          confidence=0.9, parser_name="test", parser_version="1")
    db.add(profile); db.commit()
    ws_b, run_b = _build_ws(db, ub, "工程B", "9.9-b")
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
    """模块级：临时文件 DB + 真实 MCP Server 子进程（uploads 用 pytest 临时目录）。"""
    tmp_root = tmp_path_factory.mktemp("v5a2_mcp")
    db_path = tmp_root / "mcp.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    upload_dir = tmp_root / "uploads"
    original_upload = settings.upload_dir
    object.__setattr__(settings, "upload_dir", str(upload_dir))
    try:
        data = _build_db(db_url, upload_dir)
    except Exception:
        object.__setattr__(settings, "upload_dir", original_upload)
        raise

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    secret = "v5a2-secret-" + uuid.uuid4().hex[:16]
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
    yield {"url": url, "secret": secret, "data": data, "proc": proc,
           "out_file": out_file, "db_url": db_url, "port": port,
           "upload_dir": upload_dir}

    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    finally:
        object.__setattr__(settings, "upload_dir", original_upload)


def _open_db(mcp_env):
    engine = create_engine(mcp_env["db_url"], connect_args={"check_same_thread": False})
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return S()


def _set_mcp_enabled(mcp_env, enabled: bool):
    object.__setattr__(settings, "engineering_mcp_enabled", enabled)
    object.__setattr__(settings, "engineering_mcp_url", mcp_env["url"])
    object.__setattr__(settings, "engineering_mcp_internal_token", mcp_env["secret"])


@pytest.fixture(autouse=True)
def _mcp_on(mcp_env):
    """默认开启 MCP 并指向真实 Server。"""
    _set_mcp_enabled(mcp_env, True)
    yield
    object.__setattr__(settings, "engineering_mcp_enabled", False)


def _run_verification(db, mcp_env, *, user_id, workspace_id, run_id,
                      max_tool_calls=5, actor_user_id=None, fresh_run=False):
    from app.services.engineering_verification_service import run_verification

    target_run_id = run_id
    if fresh_run:
        snap = _snapshot_json(SNAPSHOT_RULE, f"9.9-fresh-{uuid.uuid4().hex[:6]}")
        new_run = ReviewRun(workspace_id=workspace_id, owner_user_id=user_id,
                            review_template_key="engineering_bid_review_v1", status="completed",
                            rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-fresh",
                            rule_pack_hash=_snapshot_hash(snap), rule_snapshot_json=snap,
                            review_brief_id=None, review_brief_hash="b" * 64,
                            review_brief_snapshot_json="{}")
        db.add(new_run); db.commit()
        new_f = ReviewFinding(review_run_id=new_run.id, workspace_id=workspace_id,
                              owner_user_id=user_id, issue_code="SYN-TEST-001", title="资质有效期",
                              category="required_field", severity="high", conclusion="C",
                              suggestion="S", rule_id="SYN-TEST-001", rule_version="1",
                              evidence_ids_json="[]", status="pending_review")
        db.add(new_f); db.commit()
        target_run_id = new_run.id

    return run_verification(
        db, workspace_id=workspace_id, owner_user_id=user_id, review_run_id=target_run_id,
        use_deepseek=False, max_tool_calls=max_tool_calls,
        actor_user_id=actor_user_id if actor_user_id is not None else user_id,
    )


def _tool_calls_for_run(db, verification_id):
    return list(db.scalars(
        select(ReviewToolCall).where(ReviewToolCall.verification_run_id == verification_id)
        .order_by(ReviewToolCall.id.asc())
    ).all())


# ── 1-2. disabled 语义 ─────────────────────────────────────────────


class _IndexIsolationMixin:
    """所有会触发检索的测试统一隔离 _INDEX_ROOT 到 pytest 临时目录。"""

    @pytest.fixture(autouse=True)
    def _isolate_index(self, monkeypatch, tmp_path):
        from app.retrieval.embedding import FakeEmbeddingProvider

        import app.services.engineering_retrieval_service as _svc

        idx_root = tmp_path / "idx" / "workspaces"
        idx_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(_svc, "_INDEX_ROOT", idx_root, raising=True)
        monkeypatch.setattr(
            _svc, "LocalEmbeddingProvider",
            lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42),
            raising=True,
        )
        yield


class TestMCPDisabled(_IndexIsolationMixin):
    def test_disabled_zero_network(self, mcp_env, monkeypatch):
        """MCP disabled 时零网络调用（无 MCP ToolCall、无 mcp_context）。"""
        _set_mcp_enabled(mcp_env, False)
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, reused = _run_verification(db, mcp_env, user_id=d["user_a"],
                                           workspace_id=d["workspace_a"], run_id=d["run_a"])
        assert reused is False
        assert result["mcp_tool_call_count"] == 0
        assert result["mcp_enabled"] is False
        plan = result["plan"]
        assert "mcp_context" not in plan
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        assert all(c.node_name != "mcp_preflight" for c in calls)
        db.close()

    def test_disabled_4c2_behavior_unchanged(self, mcp_env):
        """disabled 时 4C-2 行为不变：候选检索正常、无 MCP 计数。"""
        _set_mcp_enabled(mcp_env, False)
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        # disabled: no mcp_context, no mcp ToolCall, budget semantics unchanged
        result, reused = _run_verification(db, mcp_env, user_id=d["user_a"],
                                           workspace_id=d["workspace_a"], run_id=d["run_a"],
                                           fresh_run=True)
        assert "mcp_context" not in result["plan"]
        assert result["mcp_tool_call_count"] == 0
        assert result["mcp_enabled"] is False
        assert result["retrieval_budget"] == 5
        db.close()


# ── 3-9. enabled 语义 ──────────────────────────────────────────────


class TestMCPEnabled(_IndexIsolationMixin):
    def test_enabled_real_calls_two_tools(self, mcp_env):
        """enabled 时真实调用两个 MCP 工具并持久化。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, reused = _run_verification(db, mcp_env, user_id=d["user_a"],
                                           workspace_id=d["workspace_a"], run_id=d["run_a"])
        assert reused is False
        assert result["mcp_tool_call_count"] == 2
        plan = result["plan"]
        assert "mcp_context" in plan
        ctx = plan["mcp_context"]
        assert ctx["enabled"] is True
        assert "run_bid_consistency_checks" in ctx["results"]
        assert "search_review_rules" in ctx["results"]
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        assert {c.tool_name for c in mcp_calls} == {
            "run_bid_consistency_checks", "search_review_rules"}
        assert all(c.status == "success" for c in mcp_calls)
        db.close()

    def test_mcp_calls_not_in_retrieval_budget(self, mcp_env):
        """MCP 调用不占 retrieval budget。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"],
                                      max_tool_calls=1)
        assert result["retrieval_budget"] == 1
        assert result["mcp_tool_call_count"] == 2
        assert result["retrieval_tool_call_count"] <= 1
        assert result["total_tool_call_count"] == result["mcp_tool_call_count"] + result["retrieval_tool_call_count"]
        db.close()

    def test_input_output_no_token(self, mcp_env):
        """MCP ToolCall input/output 不含 token/secret。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"])
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        secret = mcp_env["secret"]
        for c in mcp_calls:
            assert secret not in (c.input_json or "")
            assert secret not in (c.output_json or "")
            assert "Authorization" not in (c.input_json or "")
        db.close()

    def test_actor_user_a_cannot_use_b(self, mcp_env):
        """用户 A 不能借 Verification service 调用用户 B workspace。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        from app.services.engineering_verification_service import VerificationServiceError

        with pytest.raises(VerificationServiceError) as exc:
            _run_verification(db, mcp_env, user_id=d["user_a"],
                              workspace_id=d["workspace_b"], run_id=d["run_b"],
                              actor_user_id=d["user_a"])
        assert exc.value.code == "REVIEW_RUN_NOT_FOUND"
        db.close()

    def test_actor_user_b_own_success(self, mcp_env):
        """用户 B 用自己身份调用自己 workspace 成功。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, _ = _run_verification(db, mcp_env, user_id=d["user_b"],
                                      workspace_id=d["workspace_b"], run_id=d["run_b"])
        assert result["mcp_tool_call_count"] == 2
        db.close()

    def test_mcp_context_in_plan_json(self, mcp_env):
        """成功结果写入 plan_json.mcp_context。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"])
        vr = db.scalar(select(ReviewVerificationRun).where(
            ReviewVerificationRun.id == result["verification_run_id"]))
        plan = json.loads(vr.plan_json)
        assert "mcp_context" in plan
        ctx = plan["mcp_context"]
        assert ctx["results"]["run_bid_consistency_checks"]["status"] == "ok"
        assert ctx["results"]["search_review_rules"]["status"] == "ok"
        db.close()


# ── 10-19. 局部重试 ────────────────────────────────────────────────


class TestMCPRetry(_IndexIsolationMixin):
    @pytest.fixture(autouse=True)
    def _reset_each(self):
        _reset_fail_state()
        yield
        _reset_fail_state()

    def _verify_with_mcp_override(self, mcp_env, monkeypatch, behavior):
        """behavior: callable(client, tool_name, arguments) → 决定结果。"""
        return _mcp_override(mcp_env, monkeypatch, behavior)

    def test_consistency_ok_rule_fails_only_rule_retried(self, mcp_env, monkeypatch):
        """consistency 成功、rule search 失败 → 只重试 rule search。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _rule_fail_once)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"], fresh_run=True)
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        consistency = [c for c in mcp_calls if c.tool_name == "run_bid_consistency_checks"]
        rules = [c for c in mcp_calls if c.tool_name == "search_review_rules"]
        # consistency 只出现一次成功（不重复）
        assert len(consistency) == 1 and consistency[0].status == "success"
        # rule 失败一次 + 重试一次成功
        assert len(rules) == 2
        assert rules[0].status == "failed"
        assert rules[1].status == "success"
        assert rules[1].attempt_number == 2
        assert rules[1].retry_of_id == rules[0].id
        assert result["mcp_retry_count"] == 1
        db.close()

    def test_timeout_retried_once(self, mcp_env, monkeypatch):
        """timeout 重试一次。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _timeout_once)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"], fresh_run=True)
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        # 两工具各失败一次（TIMEOUT attempt1），各重试一次成功
        failed1 = [c for c in mcp_calls if c.status == "failed" and c.attempt_number == 1]
        assert len(failed1) == 1  # only rule search failed once
        assert failed1[0].error_code == MCPErrorCode.TIMEOUT
        retried = [c for c in mcp_calls if c.attempt_number == 2]
        assert len(retried) == 1
        assert retried[0].status == "success"
        assert retried[0].retry_of_id == failed1[0].id
        db.close()

    def test_unavailable_retried_once(self, mcp_env, monkeypatch):
        """unavailable 重试一次。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _unavailable_once)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"], fresh_run=True)
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        failed1 = [c for c in mcp_calls if c.status == "failed" and c.attempt_number == 1]
        assert len(failed1) == 1  # only rule search failed once
        assert failed1[0].error_code == MCPErrorCode.UNAVAILABLE
        retried = [c for c in mcp_calls if c.attempt_number == 2]
        assert len(retried) == 1
        assert retried[0].status == "success"
        db.close()

    def test_response_invalid_not_retried(self, mcp_env, monkeypatch):
        """response invalid 不重试。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _always_response_invalid)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"], fresh_run=True)
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        assert len(mcp_calls) == 2  # 两工具各一次，无重试
        assert all(c.attempt_number == 1 for c in mcp_calls)
        assert all(c.status == "failed" for c in mcp_calls)
        assert result["mcp_retry_count"] == 0
        db.close()

    def test_owner_error_not_retried(self, mcp_env, monkeypatch):
        """调用者归属错误不重试。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _always_owner_error)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"], fresh_run=True)
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        mcp_calls = [c for c in calls if c.node_name == "mcp_preflight"]
        assert len(mcp_calls) == 2
        assert all(c.attempt_number == 1 for c in mcp_calls)
        assert result["mcp_retry_count"] == 0
        db.close()

    def test_retry_of_id_and_attempt_number(self, mcp_env, monkeypatch):
        """retry_of_id 与 attempt_number 正确。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _rule_fail_once)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"], fresh_run=True)
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        attempt2 = [c for c in calls if c.attempt_number == 2]
        assert attempt2
        for c in attempt2:
            failed1 = next(x for x in calls if x.id == c.retry_of_id)
            assert failed1.status == "failed"
            assert failed1.attempt_number == 1
        db.close()

    def test_twice_failed_completed_with_warnings(self, mcp_env, monkeypatch):
        """两次失败后 completed_with_warnings。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _always_unavailable)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"],
                                      fresh_run=True)
        assert result["status"] == "completed_with_warnings"
        ctx = result["plan"].get("mcp_context", {})
        assert ctx.get("errors"), "mcp_context errors should be recorded"
        db.close()

    def test_no_local_fallback(self, mcp_env, monkeypatch):
        """MCP 失败时无本地同名 fallback（mcp_context 不含本地实现结果）。"""
        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _always_unavailable)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"],
                                      fresh_run=True)
        ctx = result["plan"].get("mcp_context", {})
        assert ctx["results"] == {}  # 无本地实现冒充成功
        assert ctx["errors"]  # 记录了错误
        db.close()

    def test_mcp_failure_does_not_block_retrieval(self, mcp_env, monkeypatch, tmp_path):
        """MCP 两次失败后，真实可检索流程继续并产生候选证据。"""
        from app.services.engineering_retrieval_service import rebuild_index
        from app.retrieval.embedding import FakeEmbeddingProvider
        import app.services.engineering_retrieval_service as svc_mod

        db, d = self._verify_with_mcp_override(mcp_env, monkeypatch, _always_unavailable)
        # 用真实 markdown 文件构建可检索 corpus（fl 已是真实文件）
        idx_root = tmp_path / "idx" / "workspaces"
        idx_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(svc_mod, "_INDEX_ROOT", idx_root, raising=True)
        monkeypatch.setattr(svc_mod, "LocalEmbeddingProvider",
                            lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42))
        assert svc_mod._INDEX_ROOT == idx_root, "_INDEX_ROOT monkeypatch 未生效"
        rebuild_index(db, d["workspace_a"], d["user_a"])

        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"],
                                      fresh_run=True)
        # MCP 失败（含重试仍失败）→ completed_with_warnings
        assert result["status"] == "completed_with_warnings"
        assert result["mcp_tool_call_count"] >= 4  # 两工具 × (attempt1 + retry)
        # 检索继续执行：存在成功的 engineering_hybrid_retrieval ToolCall
        calls = _tool_calls_for_run(db, result["verification_run_id"])
        retrieval_success = [c for c in calls
                             if c.node_name != "mcp_preflight"
                             and c.status == "success"
                             and c.tool_name == "engineering_hybrid_retrieval"]
        assert retrieval_success, "缺少成功的混合检索 ToolCall"
        # 候选证据 > 0
        assert result["candidate_count"] > 0
        # 计数分离
        assert result["retrieval_tool_call_count"] >= 1
        assert result["mcp_tool_call_count"] >= 4
        assert result["total_tool_call_count"] == (
            result["mcp_tool_call_count"] + result["retrieval_tool_call_count"]
        )
        db.close()


# ── 20-28. 幂等与不变 ──────────────────────────────────────────────


class TestIdempotencyAndImmutability(_IndexIsolationMixin):
    def test_hash_differs_enabled_vs_disabled(self, mcp_env):
        """MCP 开启/关闭 hash 不同。"""
        from app.services.engineering_verification_service import compute_input_state_hash

        db = _open_db(mcp_env)
        d = mcp_env["data"]
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == d["run_a"]))
        findings = list(db.scalars(select(ReviewFinding).where(
            ReviewFinding.review_run_id == run.id)).all())
        h_on = compute_input_state_hash(
            review_run_id=run.id, review_brief_hash=run.review_brief_hash,
            rule_pack_hash=run.rule_pack_hash, findings=findings,
            corpus_sha256="c", index_sha256="i",
            use_deepseek=False, max_tool_calls=5, mcp_enabled=True)
        h_off = compute_input_state_hash(
            review_run_id=run.id, review_brief_hash=run.review_brief_hash,
            rule_pack_hash=run.rule_pack_hash, findings=findings,
            corpus_sha256="c", index_sha256="i",
            use_deepseek=False, max_tool_calls=5, mcp_enabled=False)
        assert h_on != h_off
        db.close()

    def test_success_reused_true(self, mcp_env, monkeypatch, tmp_path):
        """MCP 成功且状态未变时重复请求 reused=true。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        from app.services.engineering_retrieval_service import rebuild_index
        from app.retrieval.embedding import FakeEmbeddingProvider
        import app.services.engineering_retrieval_service as _svc

        # 先建索引（mixin 隔离目录内），使两次请求间索引状态稳定
        idx_root = tmp_path / "idx" / "ws"
        idx_root.mkdir(parents=True)
        monkeypatch.setattr(_svc, "_INDEX_ROOT", idx_root, raising=True)
        monkeypatch.setattr(_svc, "LocalEmbeddingProvider",
                            lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42))
        rebuild_index(db, d["workspace_a"], d["user_a"])

        r1, reused1 = _run_verification(db, mcp_env, user_id=d["user_a"],
                                        workspace_id=d["workspace_a"], run_id=d["run_a"],
                                        fresh_run=True)
        assert reused1 is False
        recent = db.scalars(
            select(ReviewRun).where(ReviewRun.workspace_id == d["workspace_a"])
            .order_by(ReviewRun.id.desc())
        ).first()
        r2, reused2 = _run_verification(db, mcp_env, user_id=d["user_a"],
                                        workspace_id=d["workspace_a"], run_id=recent.id)
        assert reused2 is True
        assert r2["verification_run_id"] == r1["verification_run_id"]
        db.close()

    def test_warning_run_can_retry(self, mcp_env, monkeypatch):
        """瞬时失败的 warning Run 可再次创建（不永久阻止）。"""
        db, d = _mcp_override(mcp_env, monkeypatch, _always_unavailable)
        r1, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                  workspace_id=d["workspace_a"], run_id=d["run_a"],
                                  fresh_run=True)
        assert r1["status"] == "completed_with_warnings"
        # 恢复 MCP 后对同一 fresh run 再次请求 → 新 VerificationRun（warning 不参与幂等）
        from app.mcp.review_tools_client import ReviewToolsMCPClient as _RC2

        monkeypatch.setattr(_RC2, "call_tool_sync", _RC2.call_tool_sync)
        _reset_fail_state()
        recent = db.scalars(
            select(ReviewRun).where(ReviewRun.workspace_id == d["workspace_a"])
            .order_by(ReviewRun.id.desc())
        ).first()
        r2, reused2 = _run_verification(db, mcp_env, user_id=d["user_a"],
                                        workspace_id=d["workspace_a"], run_id=recent.id)
        assert reused2 is False
        assert r2["verification_run_id"] != r1["verification_run_id"]
        db.close()

    def test_finding_unchanged(self, mcp_env):
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        before = db.scalar(select(ReviewFinding).where(ReviewFinding.id == d["finding_a"]))
        before_state = (before.status, before.conclusion, before.suggestion,
                        before.evidence_ids_json, before.severity)
        _run_verification(db, mcp_env, user_id=d["user_a"],
                          workspace_id=d["workspace_a"], run_id=d["run_a"])
        after = db.scalar(select(ReviewFinding).where(ReviewFinding.id == d["finding_a"]))
        after_state = (after.status, after.conclusion, after.suggestion,
                       after.evidence_ids_json, after.severity)
        assert after_state == before_state
        db.close()

    def test_evidence_unchanged(self, mcp_env):
        db = _open_db(mcp_env)
        before_ids = [e.id for e in db.scalars(select(Evidence)).all()]
        d = mcp_env["data"]
        _run_verification(db, mcp_env, user_id=d["user_a"],
                          workspace_id=d["workspace_a"], run_id=d["run_a"])
        after_ids = [e.id for e in db.scalars(select(Evidence)).all()]
        assert after_ids == before_ids
        db.close()

    def test_report_unchanged(self, mcp_env):
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        rep = db.scalar(select(ReviewReport).where(ReviewReport.id == d["report_id"]))
        before = (rep.version, rep.review_state_hash, rep.review_snapshot_json,
                  rep.quality_gate_json, rep.status)
        _run_verification(db, mcp_env, user_id=d["user_a"],
                          workspace_id=d["workspace_a"], run_id=d["run_a"])
        rep2 = db.scalar(select(ReviewReport).where(ReviewReport.id == d["report_id"]))
        after = (rep2.version, rep2.review_state_hash, rep2.review_snapshot_json,
                 rep2.quality_gate_json, rep2.status)
        assert after == before
        db.close()

    def test_general_still_rejected(self, mcp_env):
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        gen = Workspace(owner_user_id=d["user_a"], name="通用",
                        workspace_type="general", status="active")
        db.add(gen); db.commit()
        gid = gen.id
        db.close()
        db = _open_db(mcp_env)
        from app.services.engineering_verification_service import VerificationServiceError
        with pytest.raises(VerificationServiceError) as exc:
            _run_verification(db, mcp_env, user_id=d["user_a"],
                              workspace_id=gid, run_id=d["run_a"])
        assert exc.value.code == "REVIEW_RUN_NOT_FOUND"
        db.close()


# ── behavior helpers ────────────────────────────────────────────────


def _reset_fail_state():
    _rule_fail_state["n"] = 0
    _timeout_state["n"] = 0
    _unavailable_state["n"] = 0


def _mcp_override(mcp_env, monkeypatch, behavior):
    _reset_fail_state()
    """monkeypatch ReviewToolsMCPClient.call_tool_sync 为 behavior。"""
    db = _open_db(mcp_env)
    real_call = ReviewToolsMCPClient.call_tool_sync

    def fake_call(self, tool_name, arguments):
        return behavior(self, tool_name, arguments, real_call)

    monkeypatch.setattr(ReviewToolsMCPClient, "call_tool_sync", fake_call)
    return db, mcp_env["data"]


_rule_fail_state = {"n": 0}


def _rule_fail_once(self, tool_name, arguments, real_call):
    if tool_name == "search_review_rules":
        _rule_fail_state["n"] += 1
        if _rule_fail_state["n"] == 1:
            from app.mcp.errors import unavailable
            raise unavailable()
    return real_call(self, tool_name, arguments)


_timeout_state = {"n": 0}


def _timeout_once(self, tool_name, arguments, real_call):
    if tool_name == "search_review_rules":
        _timeout_state["n"] += 1
        if _timeout_state["n"] == 1:
            from app.mcp.errors import timeout as _timeout
            raise _timeout()
    return real_call(self, tool_name, arguments)


_unavailable_state = {"n": 0}


def _unavailable_once(self, tool_name, arguments, real_call):
    if tool_name == "search_review_rules":
        _unavailable_state["n"] += 1
        if _unavailable_state["n"] == 1:
            from app.mcp.errors import unavailable
            raise unavailable()
    return real_call(self, tool_name, arguments)


def _always_response_invalid(self, tool_name, arguments, real_call):
    from app.mcp.errors import response_invalid
    raise response_invalid()


def _always_owner_error(self, tool_name, arguments, real_call):
    from app.mcp.errors import request_invalid
    raise request_invalid()


def _always_unavailable(self, tool_name, arguments, real_call):
    from app.mcp.errors import unavailable
    raise unavailable()


# ── 补修：历史 mcp_enabled / recovered vs unresolved / 非 ToolCall 警告 ─────


class TestPersistenceSemantics(_IndexIsolationMixin):
    """历史 mcp_enabled 从持久化数据读取；recovered/unresolved 区分。"""

    def _run_enabled(self, mcp_env):
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"],
                                      fresh_run=True)
        db.close()
        return result

    def test_enabled_run_stays_true_after_config_off(self, mcp_env):
        """MCP enabled Run 创建后关闭全局配置，读取旧 Run 仍显示 true。"""
        result = self._run_enabled(mcp_env)
        assert result["mcp_enabled"] is True
        object.__setattr__(settings, "engineering_mcp_enabled", False)
        try:
            db = _open_db(mcp_env)
            from app.services.engineering_verification_service import _build_result
            from app.models.review_verification_run import ReviewVerificationRun

            vr = db.scalar(select(ReviewVerificationRun).where(
                ReviewVerificationRun.id == result["verification_run_id"]))
            detail = _build_result(db, vr, reused=False)
            assert detail["mcp_enabled"] is True, "历史 enabled Run 应保持 true"
            db.close()
        finally:
            object.__setattr__(settings, "engineering_mcp_enabled", True)

    def test_disabled_run_stays_false_after_config_on(self, mcp_env):
        """MCP disabled Run 创建后打开配置，读取旧 Run 仍显示 false。"""
        _set_mcp_enabled(mcp_env, False)
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"],
                                      fresh_run=True)
        assert result["mcp_enabled"] is False
        _set_mcp_enabled(mcp_env, True)
        try:
            from app.services.engineering_verification_service import _build_result
            from app.models.review_verification_run import ReviewVerificationRun

            vr = db.scalar(select(ReviewVerificationRun).where(
                ReviewVerificationRun.id == result["verification_run_id"]))
            detail = _build_result(db, vr, reused=False)
            assert detail["mcp_enabled"] is False, "历史 disabled Run 应保持 false"
            db.close()
        finally:
            _set_mcp_enabled(mcp_env, True)

    def test_list_and_detail_consistent(self, mcp_env):
        """列表与详情结果 mcp_enabled 一致。"""
        result = self._run_enabled(mcp_env)
        db = _open_db(mcp_env)
        from app.services.engineering_verification_service import list_verification_runs

        d = mcp_env["data"]
        recent = db.scalars(
            select(ReviewRun).where(ReviewRun.workspace_id == d["workspace_a"])
            .order_by(ReviewRun.id.desc())
        ).first()
        runs = list_verification_runs(db, d["workspace_a"], d["user_a"], recent.id)
        assert runs, "列表应有 run"
        assert runs[0]["mcp_enabled"] is True
        assert runs[0]["mcp_enabled"] == result["mcp_enabled"]
        db.close()

    def test_recovered_error_completed_and_reusable(self, mcp_env, monkeypatch):
        """attempt1 失败 + attempt2 成功 → recovered_errors、completed、可幂等。"""
        db, d = _mcp_override(mcp_env, monkeypatch, _unavailable_once)
        # 先建索引稳定状态（mixin 隔离目录内，FakeEmbedding）
        from app.services.engineering_retrieval_service import rebuild_index
        from app.retrieval.embedding import FakeEmbeddingProvider
        import app.services.engineering_retrieval_service as _svc

        monkeypatch.setattr(_svc, "LocalEmbeddingProvider",
                            lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42))
        rebuild_index(db, d["workspace_a"], d["user_a"])
        r1, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                  workspace_id=d["workspace_a"], run_id=d["run_a"],
                                  fresh_run=True)
        assert r1["status"] == "completed"
        assert r1["warning_count"] == 0
        assert r1["warnings"] == [], f"已恢复错误不应产生警告: {r1['warnings']}"
        ctx = r1["plan"]["mcp_context"]
        assert ctx.get("errors") == [], f"不应有未解决错误: {ctx.get('errors')}"
        assert ctx.get("recovered_errors"), "应记录 recovered_errors"
        assert any(e["error_code"] == MCPErrorCode.UNAVAILABLE for e in ctx["recovered_errors"])
        recent = db.scalars(
            select(ReviewRun).where(ReviewRun.workspace_id == d["workspace_a"])
            .order_by(ReviewRun.id.desc())
        ).first()
        # 恢复 MCP 真实调用（移除 fail-once 的 call_tool_sync 覆盖）
        from app.mcp.review_tools_client import ReviewToolsMCPClient as _RC

        monkeypatch.setattr(_RC, "call_tool_sync", _RC.call_tool_sync)
        r2, reused2 = _run_verification(db, mcp_env, user_id=d["user_a"],
                                        workspace_id=d["workspace_a"], run_id=recent.id)
        assert reused2 is True
        assert r2["verification_run_id"] == r1["verification_run_id"]
        db.close()

    def test_unresolved_error_warning_not_reusable(self, mcp_env, monkeypatch):
        """两次均失败 → 未解决错误保留、completed_with_warnings、不参与幂等。"""
        db, d = _mcp_override(mcp_env, monkeypatch, _always_unavailable)
        r1, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                  workspace_id=d["workspace_a"], run_id=d["run_a"],
                                  fresh_run=True)
        assert r1["status"] == "completed_with_warnings"
        ctx = r1["plan"]["mcp_context"]
        assert MCPErrorCode.UNAVAILABLE in ctx.get("errors", [])
        assert r1["warnings"], f"两次失败应产生警告: {r1['warnings']}"
        assert any("MCP" in w for w in r1["warnings"]), "warnings 应含 MCP 未解决警告"
        db.close()

    def test_non_toolcall_warnings_persisted(self, mcp_env, monkeypatch):
        """capability/discovery 警告持久化在 mcp_context.warnings 并返回。"""
        db, d = _mcp_override(mcp_env, monkeypatch, _always_unavailable)
        from app.mcp.review_tools_client import ReviewToolsMCPClient as _C
        from app.mcp.errors import discovery_error as _de

        def bad_discover(self):
            raise _de()

        monkeypatch.setattr(_C, "discover_tools_sync", bad_discover)
        result, _ = _run_verification(db, mcp_env, user_id=d["user_a"],
                                      workspace_id=d["workspace_a"], run_id=d["run_a"],
                                      fresh_run=True)
        ctx = result["plan"].get("mcp_context", {})
        assert MCPErrorCode.DISCOVERY_ERROR in ctx.get("errors", [])
        assert ctx.get("warnings"), "mcp_context.warnings 应持久化"
        assert any("MCP" in w for w in result["warnings"]), "返回 warnings 应含 MCP 警告"
        db.close()


class TestRuleQueryPriority(_IndexIsolationMixin):
    """规则查询优先级从 Run 快照解析，不依赖 issue_code 字符串。"""

    def _make_run_with_types(self, mcp_env, rules):
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        snap = json.dumps({
            "pack_id": "engineering_bid_review_v1", "version": "9.9-pri",
            "title": "T", "description": "D", "disclaimer": "X", "rules": rules,
        }, ensure_ascii=False)
        run = ReviewRun(workspace_id=d["workspace_a"], owner_user_id=d["user_a"],
                        review_template_key="engineering_bid_review_v1", status="completed",
                        rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-pri",
                        rule_pack_hash=_snapshot_hash(snap), rule_snapshot_json=snap,
                        review_brief_id=None, review_brief_hash="b" * 64,
                        review_brief_snapshot_json="{}")
        db.add(run); db.commit()
        run_id_val = run.id
        for rule in rules:
            f = ReviewFinding(review_run_id=run_id_val, workspace_id=d["workspace_a"],
                              owner_user_id=d["user_a"], issue_code=rule["rule_id"],
                              title=rule["title"], category="x",
                              severity=rule["severity"], conclusion="C", suggestion="S",
                              rule_id=rule["rule_id"], rule_version="1",
                              evidence_ids_json="[]", status="pending_review")
            db.add(f); db.commit()
        db.close()
        return run_id_val

    def _query_for_run(self, mcp_env, run_id):
        db = _open_db(mcp_env)
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == run_id))
        findings = list(db.scalars(select(ReviewFinding).where(
            ReviewFinding.review_run_id == run_id)).all())
        from app.services.engineering_verification_service import _build_mcp_search_query
        query = _build_mcp_search_query(findings, run)
        db.close()
        return query

    def test_evidence_required_priority_from_snapshot(self, mcp_env):
        """evidence_required 类型（经快照映射）优先，即使 issue_code 不含该词。"""
        rules = [
            {"rule_id": "SYN-A", "version": "1", "type": "cross_file_equal",
             "title": "证书一致性", "description": "D", "severity": "medium",
             "inputs": {}, "parameters": {},
             "source_kind": "synthetic_tender_clause", "source_locator": "1",
             "suggestion": "S"},
            {"rule_id": "SYN-B", "version": "1", "type": "evidence_required",
             "title": "证据要求", "description": "D", "severity": "low",
             "inputs": {}, "parameters": {},
             "source_kind": "synthetic_tender_clause", "source_locator": "2",
             "suggestion": "S"},
        ]
        run_id = self._make_run_with_types(mcp_env, rules)
        q = self._query_for_run(mcp_env, run_id)
        assert "SYN-B" in q, f"evidence_required 应优先: {q}"
        assert "SYN-A" not in q, f"query 应只含优先级最高 Finding: {q}"

    def test_cross_file_second(self, mcp_env):
        """cross_file_equal 高于 high severity。"""
        rules = [
            {"rule_id": "SYN-C", "version": "1", "type": "cross_file_equal",
             "title": "跨文件", "description": "D", "severity": "medium",
             "inputs": {}, "parameters": {},
             "source_kind": "synthetic_tender_clause", "source_locator": "1",
             "suggestion": "S"},
            {"rule_id": "SYN-H", "version": "1", "type": "required_field",
             "title": "高风险", "description": "D", "severity": "high",
             "inputs": {}, "parameters": {},
             "source_kind": "synthetic_tender_clause", "source_locator": "2",
             "suggestion": "S"},
        ]
        run_id = self._make_run_with_types(mcp_env, rules)
        q = self._query_for_run(mcp_env, run_id)
        assert "SYN-C" in q, f"cross_file 应优先: {q}"
        assert "SYN-H" not in q, f"query 应只含 cross_file Finding: {q}"

    def test_disk_rule_change_does_not_affect(self, mcp_env, monkeypatch):
        """磁盘规则变化不改变已有 Run 的查询选择（快照为准）。"""
        import app.services.review_rule_service as rrs
        from app.schemas.review import ReviewRulePack

        rules = [
            {"rule_id": "SYN-E", "version": "1", "type": "evidence_required",
             "title": "证据", "description": "D", "severity": "medium",
             "inputs": {}, "parameters": {},
             "source_kind": "synthetic_tender_clause", "source_locator": "1",
             "suggestion": "S"},
            {"rule_id": "SYN-F", "version": "1", "type": "required_field",
             "title": "字段", "description": "D", "severity": "high",
             "inputs": {}, "parameters": {},
             "source_kind": "synthetic_tender_clause", "source_locator": "2",
             "suggestion": "S"},
        ]
        run_id = self._make_run_with_types(mcp_env, rules)

        def _changed(*a, **kw):
            changed = [dict(r) for r in rules]
            changed[0]["type"] = "required_field"
            changed[1]["type"] = "evidence_required"
            return ReviewRulePack.model_validate({
                "pack_id": "engineering_bid_review_v1", "version": "999",
                "title": "T", "description": "D", "disclaimer": "X", "rules": changed,
            })

        monkeypatch.setattr(rrs, "load_rule_pack", _changed)
        q = self._query_for_run(mcp_env, run_id)
        assert "SYN-E" in q, f"快照为准，应选 SYN-E: {q}"

    def test_broken_snapshot_safe_strategy(self, mcp_env):
        """快照损坏时安全策略：按 severity/id 兜底（不失败、不读磁盘）。"""
        db = _open_db(mcp_env)
        d = mcp_env["data"]
        run = ReviewRun(workspace_id=d["workspace_a"], owner_user_id=d["user_a"],
                        review_template_key="engineering_bid_review_v1", status="completed",
                        rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9-x",
                        rule_pack_hash="a" * 64, rule_snapshot_json="{{broken",
                        review_brief_id=None, review_brief_hash="b" * 64,
                        review_brief_snapshot_json="{}")
        db.add(run); db.commit()
        for sev in ("high", "medium"):
            f = ReviewFinding(review_run_id=run.id, workspace_id=d["workspace_a"],
                              owner_user_id=d["user_a"], issue_code=f"SYN-{sev}",
                              title=f"T{sev}", category="x", severity=sev,
                              conclusion="C", suggestion="S", rule_id=f"SYN-{sev}",
                              rule_version="1", evidence_ids_json="[]",
                              status="pending_review")
            db.add(f); db.commit()
        run_id = run.id
        db.close()
        q = self._query_for_run(mcp_env, run_id)
        assert "SYN-high" in q, f"快照损坏安全策略应选 high: {q}"
