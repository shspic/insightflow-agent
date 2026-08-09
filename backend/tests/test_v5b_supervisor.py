"""阶段 5B：Engineering Supervisor 编排与确定性质量门专项测试。

普通 pytest 完全离线：不调用 DeepSeek、不加载真实 BGE、不访问公网。
隔离 SQLite（文件临时库）+ pytest 临时 uploads/retrieval；
每次调用使用独立 fresh ReviewRun（避免共享状态污染）；
不写默认 app.db/uploads/reports/retrieval；无 mkdtemp 独立残留；无递归删除。
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

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.mcp.review_tools_server import run_review_tools_server
from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_brief import ReviewBrief
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_run import ReviewRun
from app.models.review_supervisor_run import ReviewSupervisorRun
from app.models.review_supervisor_step import ReviewSupervisorStep
from app.models.review_verification_run import ReviewVerificationRun
from app.models.review_report_asset import ReviewReportAsset
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.models.file_profile import FileProfile
from app.services.security_service import hash_password

BACKEND_DIR = Path(__file__).resolve().parents[1]

ROLES = ("tender_requirement", "bid_response", "personnel_equipment_data",
         "qualification_attachment", "clarification_document")

RULE_TEMPLATE = {
    "rule_id": "SYN-NUM-001", "version": "1", "type": "numeric_threshold",
    "title": "人员数量", "description": "人员至少 5 人", "severity": "high",
    "inputs": {}, "parameters": {"field": "total_personnel", "threshold": 5, "operator": "gte"},
    "source_kind": "synthetic_tender_clause", "source_locator": "1", "suggestion": "请核对",
}


def _snapshot_json(rules=None, version="9.9") -> str:
    return json.dumps({
        "pack_id": "engineering_bid_review_v1", "version": version,
        "title": "T", "description": "D", "disclaimer": "X",
        "rules": rules or [RULE_TEMPLATE],
    }, ensure_ascii=False)


def _snapshot_hash(snap: str) -> str:
    return hashlib.sha256(snap.encode("utf-8")).hexdigest()


def _build_db(db_url: str, upload_dir: Path):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()
    upload_dir.mkdir(parents=True, exist_ok=True)

    u = User(username="v5b_user", password_hash=hash_password("SafePassword!2026"),
             role="user", status="active", must_change_password=False)
    db.add(u); db.commit()
    ws = Workspace(owner_user_id=u.id, name="工程", workspace_type="engineering",
                   review_template_key="engineering_bid_review_v1", status="active")
    db.add(ws); db.commit()
    file_ids = {}
    for i, role in enumerate(ROLES):
        real_md = upload_dir / f"f{i}.md"
        real_md.write_text(f"角色 {role} 材料", encoding="utf-8")
        fl = File(owner_user_id=u.id, filename=f"f{i}.md", file_type="markdown",
                  file_path=str(real_md), status="ready")
        db.add(fl); db.commit()
        wf = WorkspaceFile(workspace_id=ws.id, file_id=fl.id, user_confirmed_role=role)
        db.add(wf); db.commit()
        prof = FileProfile(workspace_id=ws.id, file_id=fl.id, owner_user_id=u.id,
                           profile_version=1, status="ready", confirmed_role=role,
                           suggested_role=role, file_category="document", language="zh",
                           title=role, summary=role, confidence=0.9,
                           parser_name="p", parser_version="1")
        db.add(prof); db.commit()
        file_ids[role] = fl.id

    brief = ReviewBrief(workspace_id=ws.id, owner_user_id=u.id, version=1,
                        raw_requirements="审查", interpreted_json="{}", status="confirmed",
                        interpreter_type="deterministic_fixture", content_hash="a" * 64)
    db.add(brief); db.commit()
    data = {"user": u.id, "workspace": ws.id, "file_ids": file_ids,
            "brief": brief.id, "brief_snapshot": json.dumps(
                {"id": brief.id, "version": 1, "content_hash": "a" * 64,
                 "raw_requirements": "审查", "interpreted_json": "{}"})}
    db.close()
    engine.dispose()
    return data


def _fresh_run(db, d, *, evidence_json="[1]", rule_version="1", rule_id="SYN-NUM-001",
               source_step_id="engine:SYN-NUM-001", snapshot_json=None):
    snap = snapshot_json if snapshot_json is not None else _snapshot_json()
    brief_snap = d["brief_snapshot"]
    run = ReviewRun(workspace_id=d["workspace"], owner_user_id=d["user"],
                    review_template_key="engineering_bid_review_v1", status="completed",
                    rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9",
                    rule_pack_hash=_snapshot_hash(snap), rule_snapshot_json=snap,
                    review_brief_id=d["brief"], review_brief_version=1,
                    review_brief_hash=hashlib.sha256(brief_snap.encode()).hexdigest(),
                    review_brief_snapshot_json=brief_snap)
    db.add(run); db.commit()
    run_id = run.id
    # 阶段 6A 契约：Evidence 必须携带来源完整性字段。
    # content_hash = 证据记录规范哈希（7 字段公式，与 create_evidence 一致）；
    # source_file_hash = 真实来源文件字节 SHA-256；provenance=field_locator。
    from app.services.review_engine_service import _compute_evidence_hash
    from app.services.evidence_provenance import FIELD_LOCATOR, compute_file_sha256_safe

    target_md = Path(settings.upload_dir) / "f2.md"
    ev_file_id = d["file_ids"]["personnel_equipment_data"]
    ev_data = {
        "file_id": ev_file_id, "locator_type": "text_chunk",
        "page_number": None, "sheet_name": None, "cell_range": None,
        "chunk_id": 0, "quote": "人员数量 4",
    }
    ev = Evidence(review_run_id=run_id, workspace_id=d["workspace"], owner_user_id=d["user"],
                  file_id=ev_file_id, locator_type="text_chunk",
                  chunk_id=0, quote="人员数量 4",
                  content_hash=_compute_evidence_hash(ev_data),
                  provenance_type=FIELD_LOCATOR,
                  source_file_hash=compute_file_sha256_safe(str(target_md)),
                  parser_name="p", parser_version="1")
    db.add(ev); db.commit()
    ev_id = ev.id
    if evidence_json == "[1]":
        evidence_json = f"[{ev_id}]"
    f = ReviewFinding(review_run_id=run_id, workspace_id=d["workspace"], owner_user_id=d["user"],
                      issue_code="SYN-NUM-001", title="人员数量", category="numeric_threshold",
                      severity="high", conclusion="人员数量不足", suggestion="请核对",
                      rule_id=rule_id, rule_version=rule_version, evidence_ids_json=evidence_json,
                      status="pending_review", source_step_id=source_step_id)
    db.add(f); db.commit()
    return run_id


@pytest.fixture(scope="module")
def sup_env(tmp_path_factory):
    tmp_root = tmp_path_factory.mktemp("v5b_mcp")
    db_path = tmp_root / "mcp.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    upload_dir = tmp_root / "uploads"
    original_upload = settings.upload_dir
    original_report = settings.report_dir
    object.__setattr__(settings, "upload_dir", str(upload_dir))
    object.__setattr__(settings, "report_dir", str(tmp_root / "reports"))
    try:
        data = _build_db(db_url, upload_dir)
    except Exception:
        object.__setattr__(settings, "upload_dir", original_upload)
        object.__setattr__(settings, "report_dir", original_report)
        raise

    import app.services.engineering_retrieval_service as svc_mod
    from app.retrieval.embedding import FakeEmbeddingProvider

    idx_root = tmp_root / "retrieval" / "workspaces"
    idx_root.mkdir(parents=True)
    original_index_root = svc_mod._INDEX_ROOT
    svc_mod._INDEX_ROOT = idx_root
    svc_mod.LocalEmbeddingProvider = lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42)
    from app.services.engineering_retrieval_service import rebuild_index
    eng = create_engine(db_url, connect_args={"check_same_thread": False})
    S = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    dbs = S()
    _fresh_run(dbs, data)
    rebuild_index(dbs, data["workspace"], data["user"])
    dbs.close(); eng.dispose()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    secret = "v5b-secret-" + uuid.uuid4().hex[:16]
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
        proc = subprocess.Popen([sys.executable, "-c", server_code], env=env, cwd=BACKEND_DIR,
                                stdout=fout, stderr=subprocess.STDOUT)
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
            log = open(out_file, encoding="utf-8", errors="replace").read()[:1500]
            proc.terminate()
            pytest.fail(f"MCP Server 未就绪: {log}")

    url = f"http://127.0.0.1:{port}/mcp"
    object.__setattr__(settings, "engineering_mcp_enabled", True)
    object.__setattr__(settings, "engineering_mcp_url", url)
    object.__setattr__(settings, "engineering_mcp_internal_token", secret)
    yield {"url": url, "secret": secret, "data": data, "proc": proc,
           "out_file": out_file, "db_url": db_url, "port": port}

    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    finally:
        object.__setattr__(settings, "upload_dir", original_upload)
        object.__setattr__(settings, "report_dir", original_report)
        object.__setattr__(settings, "engineering_mcp_enabled", False)
        svc_mod._INDEX_ROOT = original_index_root


def _open_db(sup_env):
    engine = create_engine(sup_env["db_url"], connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return S()


def _run_supervisor(db, sup_env, *, generate_report=False, max_step_retries=1,
                    max_verification_tool_calls=5, use_deepseek=False, **finding_kw):
    from app.services.engineering_supervisor_service import run_supervisor

    d = sup_env["data"]
    run_id = _fresh_run(db, d, **finding_kw)
    return run_supervisor(
        db, workspace_id=d["workspace"], owner_user_id=d["user"], review_run_id=run_id,
        actor_user_id=d["user"], use_deepseek=use_deepseek,
        max_verification_tool_calls=max_verification_tool_calls,
        max_step_retries=max_step_retries, generate_report=generate_report,
    )


# ── 核心流程 ───────────────────────────────────────────────────────


class TestCoreFlow:
    def test_four_nodes_normal_order(self, sup_env):
        db = _open_db(sup_env)
        result, reused = _run_supervisor(db, sup_env, generate_report=False)
        assert reused is False
        assert result["status"] == "ready_to_report"
        nodes = [s["node_name"] for s in result["steps"]]
        assert nodes[0] == "extraction" and nodes[1] == "verification"
        assert all(s["status"] == "success" for s in result["steps"])
        assert result["quality_gate"]["status"] == "passed"
        assert result["report_id"] is None
        db.close()

    def test_gate_passed_generate_report(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True)
        assert result["status"] == "completed"
        assert result["report_id"] is not None
        assert result["quality_gate"]["status"] == "passed"
        db.close()

    def test_supervisor_idempotent(self, sup_env):
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        from app.services.engineering_supervisor_service import run_supervisor
        r1, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                               review_run_id=run_id, actor_user_id=d["user"],
                               use_deepseek=False, max_verification_tool_calls=5,
                               max_step_retries=1, generate_report=False)
        r2, reused2 = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                     review_run_id=run_id, actor_user_id=d["user"],
                                     use_deepseek=False, max_verification_tool_calls=5,
                                     max_step_retries=1, generate_report=False)
        assert reused2 is True
        assert r2["supervisor_run_id"] == r1["supervisor_run_id"]
        db.close()

    def test_verification_run_linked(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=False)
        assert result["verification_run_id"] is not None
        db.close()

    def test_quality_review_independent_step(self, sup_env):
        """Quality Review 必须独立记录 Step（不能只藏在 SupervisorRun JSON 中）。"""
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=False)
        nodes = [s["node_name"] for s in result["steps"]]
        assert "quality_review" in nodes
        gate_step = [s for s in result["steps"] if s["node_name"] == "quality_review"][0]
        assert gate_step["status"] == "success"
        assert gate_step["output"]["gate_status"] == "passed"
        assert gate_step["output"]["reportable_finding_ids"]
        assert gate_step["output"]["errors"] == []
        # 与 run 级 quality_gate_json 一致
        assert result["quality_gate"]["status"] == "passed"
        db.close()

    def test_input_state_hash_changes_no_reuse(self, sup_env):
        """稳定输入变化（如 max_step_retries）→ input_state_hash 变化 → 不复用。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        from app.services.engineering_supervisor_service import run_supervisor

        r1, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                               review_run_id=run_id, actor_user_id=d["user"],
                               use_deepseek=False, max_verification_tool_calls=5,
                               max_step_retries=1, generate_report=False)
        r2, reused2 = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                     review_run_id=run_id, actor_user_id=d["user"],
                                     use_deepseek=False, max_verification_tool_calls=5,
                                     max_step_retries=2, generate_report=False)
        assert reused2 is False
        assert r2["supervisor_run_id"] != r1["supervisor_run_id"]
        assert r1["input_state_hash"] != r2["input_state_hash"]
        db.close()

    def test_reused_run_steps_identical(self, sup_env):
        """幂等复用返回相同 Steps（成功步骤被复用，不重新执行）。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        from app.services.engineering_supervisor_service import run_supervisor

        r1, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                               review_run_id=run_id, actor_user_id=d["user"],
                               use_deepseek=False, max_verification_tool_calls=5,
                               max_step_retries=1, generate_report=False)
        r2, reused2 = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                     review_run_id=run_id, actor_user_id=d["user"],
                                     use_deepseek=False, max_verification_tool_calls=5,
                                     max_step_retries=1, generate_report=False)
        assert reused2 is True
        assert [s["id"] for s in r1["steps"]] == [s["id"] for s in r2["steps"]]
        assert [s["created_at"] for s in r1["steps"]] == [s["created_at"] for s in r2["steps"]]
        db.close()


# ── 质量门阻断 ─────────────────────────────────────────────────────


class TestQualityGateBlocks:
    def test_no_evidence_blocked(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True, evidence_json="[]")
        assert result["status"] == "needs_human"
        assert result["quality_gate"]["errors"] == ["EVIDENCE_MISSING"]
        assert result["report_id"] is None
        db.close()

    def test_fake_evidence_blocked(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True, evidence_json="[999]")
        assert result["quality_gate"]["errors"] == ["EVIDENCE_MISSING"]
        assert result["report_id"] is None
        db.close()

    def test_rule_version_mismatch_blocked(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True, rule_version="99")
        assert result["quality_gate"]["errors"] == ["RULE_VERSION_MISMATCH"]
        db.close()

    def test_rule_not_found_blocked(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True, rule_id="SYN-UNKNOWN")
        assert result["quality_gate"]["errors"] == ["RULE_NOT_FOUND"]
        db.close()

    def test_numeric_provenance_missing_blocked(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True, source_step_id=None)
        assert "NUMERIC_PROVENANCE_MISSING" in result["quality_gate"]["errors"]
        assert result["report_id"] is None
        db.close()

    def test_gate_fail_no_report_asset(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True, evidence_json="[]")
        assert result["report_id"] is None
        # 质量门失败不产生本次 run 的报告（共享 DB 中可能已有历史报告，仅验证本 run 无 report_id）
        db.close()

    def test_gate_failed_clarification_json(self, sup_env):
        """质量门失败必须产生结构化的 clarification（安全消息，不含内容/路径）。"""
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True, evidence_json="[]")
        assert result["status"] == "needs_human"
        assert result["clarification"]["code"] == "QUALITY_GATE_BLOCKED"
        assert result["clarification"]["issues"]
        texts = json.dumps(result["clarification"], ensure_ascii=False)
        assert "C:\\" not in texts and "Users" not in texts
        for issue in result["clarification"]["issues"]:
            assert issue["safe_message"].startswith("Finding")
        db.close()

    def test_rule_input_missing_blocked(self, sup_env):
        """规则声明了必需的结构化输入但 ReviewRun 无输入快照 → RULE_INPUT_MISSING 阻断。"""
        db = _open_db(sup_env)
        rule = dict(RULE_TEMPLATE)
        rule["inputs"] = {"field": "total_personnel"}
        snap = _snapshot_json(rules=[rule])
        result, _ = _run_supervisor(db, sup_env, generate_report=True,
                                    snapshot_json=snap)
        assert result["status"] == "needs_human"
        assert "RULE_INPUT_MISSING" in result["quality_gate"]["errors"]
        assert result["report_id"] is None
        db.close()

    def test_evidence_unchanged_passes(self, sup_env):
        """未变化的 Evidence 必须通过质量门（不误报 EVIDENCE_STALE）。"""
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=True)
        assert result["quality_gate"]["status"] == "passed"
        assert "EVIDENCE_STALE" not in result["quality_gate"]["errors"]
        assert result["status"] == "completed"
        db.close()

    # 注意：以下测试会临时修改共享 sup_env 的 f2.md 内容，必须在 finally 中恢复，
    # 否则后续测试（共享 module-scope fixture）会因 corpus 变化而误报 stale。
    ORIGINAL_F2 = "角色 personnel_equipment_data 材料"

    def test_evidence_stale_content_changed(self, sup_env):
        """原文件内容变化，locator 仍存在但 hash 改变 → EVIDENCE_STALE → needs_human。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        target = Path(settings.upload_dir) / "f2.md"
        assert target.exists()
        target.write_text("角色 personnel_equipment_data 材料 更新后的内容", encoding="utf-8")
        try:
            from app.services.engineering_supervisor_service import run_supervisor

            result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                       review_run_id=run_id, actor_user_id=d["user"],
                                       use_deepseek=False, max_verification_tool_calls=5,
                                       max_step_retries=1, generate_report=True)
            assert result["status"] == "needs_human"
            assert result["current_step"] == "quality_review"
            assert "EVIDENCE_STALE" in result["quality_gate"]["errors"]
            assert result["report_id"] is None
        finally:
            target.write_text(self.ORIGINAL_F2, encoding="utf-8")
        db.close()

    def test_evidence_stale_locator_gone(self, sup_env):
        """locator 已消失（文件内容清空）→ EVIDENCE_STALE。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        target = Path(settings.upload_dir) / "f2.md"
        target.write_text("", encoding="utf-8")
        try:
            from app.services.engineering_supervisor_service import run_supervisor

            result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                       review_run_id=run_id, actor_user_id=d["user"],
                                       use_deepseek=False, max_verification_tool_calls=5,
                                       max_step_retries=1, generate_report=True)
            assert "EVIDENCE_STALE" in result["quality_gate"]["errors"]
            assert result["status"] == "needs_human"
            assert result["report_id"] is None
        finally:
            target.write_text(self.ORIGINAL_F2, encoding="utf-8")
        db.close()

    def test_evidence_stale_no_report(self, sup_env):
        """stale 后不生成报告，也不创建任何 ReviewReport 行。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        target = Path(settings.upload_dir, "f2.md")
        target.write_text("角色 personnel_equipment_data 材料 已变更", encoding="utf-8")
        try:
            from app.services.engineering_supervisor_service import run_supervisor

            result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                       review_run_id=run_id, actor_user_id=d["user"],
                                       use_deepseek=False, max_verification_tool_calls=5,
                                       max_step_retries=1, generate_report=True)
            assert result["report_id"] is None
            assert db.query(ReviewReport).filter(ReviewReport.review_run_id == run_id).count() == 0
        finally:
            target.write_text(self.ORIGINAL_F2, encoding="utf-8")
        db.close()

    def test_evidence_stale_finding_evidence_history_unchanged(self, sup_env):
        """stale 后 Finding/Evidence/历史 Report 行均不变（只读）。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        findings_before = {f.id: (f.status, f.evidence_ids_json) for f in db.scalars(select(ReviewFinding)).all()}
        evidences_before = {e.id: (e.content_hash, e.file_id) for e in db.scalars(select(Evidence)).all()}
        reports_before = {(r.id, r.version, r.review_state_hash) for r in db.scalars(select(ReviewReport)).all()}
        target = Path(settings.upload_dir, "f2.md")
        target.write_text("角色 personnel_equipment_data 材料 变化", encoding="utf-8")
        try:
            from app.services.engineering_supervisor_service import run_supervisor

            run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                           review_run_id=run_id, actor_user_id=d["user"],
                           use_deepseek=False, max_verification_tool_calls=5,
                           max_step_retries=1, generate_report=True)
            findings_after = {f.id: (f.status, f.evidence_ids_json) for f in db.scalars(select(ReviewFinding)).all()}
            evidences_after = {e.id: (e.content_hash, e.file_id) for e in db.scalars(select(Evidence)).all()}
            reports_after = {(r.id, r.version, r.review_state_hash) for r in db.scalars(select(ReviewReport)).all()}
            assert findings_before == findings_after
            assert evidences_before == evidences_after
            assert reports_before == reports_after
        finally:
            target.write_text(self.ORIGINAL_F2, encoding="utf-8")
        db.close()

    def test_evidence_stale_error_no_path_leak(self, sup_env):
        """stale 的错误消息不得泄露外部文件路径或内部异常。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        target = Path(settings.upload_dir, "f2.md")
        target.write_text("角色 personnel_equipment_data 材料 又变了", encoding="utf-8")
        try:
            from app.services.engineering_supervisor_service import run_supervisor

            result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                       review_run_id=run_id, actor_user_id=d["user"],
                                       use_deepseek=False, max_verification_tool_calls=5,
                                       max_step_retries=1, generate_report=True)
            text = json.dumps(result, ensure_ascii=False)
            for forbidden in ("C:\\", "D:\\", "Users", "Traceback", "File ", "uploads"):
                assert forbidden not in text, f"泄露: {forbidden}"
            stale_check = [c for c in result["quality_gate"]["checks"]
                           if c["check_code"] == "EVIDENCE_STALE"]
            assert stale_check
            assert "来源文件内容已变化" in stale_check[0]["safe_message"]
        finally:
            target.write_text(self.ORIGINAL_F2, encoding="utf-8")
        db.close()

    def test_evidence_stale_related_file_ids_excluded(self, sup_env):
        """stale 的 Evidence 不得进入 related_file_ids。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        stale_file_id = d["file_ids"]["personnel_equipment_data"]
        target = Path(settings.upload_dir, "f2.md")
        target.write_text("角色 personnel_equipment_data 材料 变化", encoding="utf-8")
        try:
            from app.services.engineering_supervisor_service import run_supervisor

            result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                       review_run_id=run_id, actor_user_id=d["user"],
                                       use_deepseek=False, max_verification_tool_calls=5,
                                       max_step_retries=1, generate_report=True)
            assert stale_file_id not in result["quality_gate"]["related_file_ids"]
        finally:
            target.write_text(self.ORIGINAL_F2, encoding="utf-8")
        db.close()

    def test_stale_evidence_related_file_ids(self, sup_env, tmp_path):
        """Evidence 引用的文件不属于工作区 → EVIDENCE_INVALID，related_file_ids 不含该文件。"""
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        outside = Path(settings.upload_dir) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        foreign = File(owner_user_id=d["user"], filename="outside.txt", file_type="text",
                       file_path=str(outside), status="ready")
        db.add(foreign)
        db.commit()
        ev = db.scalar(select(Evidence).where(Evidence.review_run_id == run_id))
        ev.file_id = foreign.id
        db.commit()
        from app.services.engineering_supervisor_service import run_supervisor

        result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                   review_run_id=run_id, actor_user_id=d["user"],
                                   use_deepseek=False, max_verification_tool_calls=5,
                                   max_step_retries=1, generate_report=True)
        assert "EVIDENCE_INVALID" in result["quality_gate"]["errors"]
        assert foreign.id not in result["quality_gate"]["related_file_ids"]
        assert result["report_id"] is None
        db.close()


# ── 局部重试 ───────────────────────────────────────────────────────


class TestLocalRetry:
    def test_verification_retried_on_mcp_failure(self, sup_env, monkeypatch):
        from app.mcp.review_tools_client import ReviewToolsMCPClient as _C
        from app.mcp.errors import unavailable as _unavail

        db = _open_db(sup_env)
        real = _C.call_tool_sync
        state = {"n": 0}

        def flaky(self, tool_name, arguments):
            if tool_name == "search_review_rules" and state["n"] == 0:
                state["n"] += 1
                raise _unavail()
            return real(self, tool_name, arguments)

        monkeypatch.setattr(_C, "call_tool_sync", flaky)
        result, _ = _run_supervisor(db, sup_env, generate_report=False, max_step_retries=1)
        extraction = [s for s in result["steps"] if s["node_name"] == "extraction"]
        assert len(extraction) == 1, "extraction 不应被无关重跑"
        from app.models.review_tool_call import ReviewToolCall

        vrun_id = result["verification_run_id"]
        mcp_calls = list(db.scalars(
            select(ReviewToolCall).where(
                ReviewToolCall.verification_run_id == vrun_id,
                ReviewToolCall.node_name == "mcp_preflight",
            ).order_by(ReviewToolCall.id.asc())
        ).all())
        attempt2 = [c for c in mcp_calls if c.attempt_number == 2]
        assert attempt2, "Verification 内部应发生 MCP 重试（attempt2）"
        assert result["status"] == "ready_to_report"
        db.close()

    def test_mcp_permanent_failure_needs_human(self, sup_env, monkeypatch):
        from app.mcp.review_tools_client import ReviewToolsMCPClient as _C
        from app.mcp.errors import unavailable as _unavail

        db = _open_db(sup_env)

        def always_fail(self, tool_name, arguments):
            raise _unavail()

        monkeypatch.setattr(_C, "call_tool_sync", always_fail)
        result, _ = _run_supervisor(db, sup_env, generate_report=False, max_step_retries=1)
        assert result["status"] == "needs_human", result["status"]
        assert result["current_step"] == "verification"
        db.close()

    def test_success_step_reused(self, sup_env):
        db = _open_db(sup_env)
        result, _ = _run_supervisor(db, sup_env, generate_report=False)
        extraction = [s for s in result["steps"] if s["node_name"] == "extraction"][0]
        assert extraction["reused"] is False
        db.close()

    def test_verification_retry_of_chain(self, sup_env, monkeypatch):
        """Verification 整体失败重试必须构成 retry_of 链：attempt2.retry_of_id 指向 attempt1。"""
        import app.services.engineering_supervisor_service as sup_mod

        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        # 成功分支需要真实 VerificationRun 行（FK 引用必须有对应记录）
        vr = ReviewVerificationRun(
            workspace_id=d["workspace"], owner_user_id=d["user"], review_run_id=run_id,
            status="completed", input_state_hash="a" * 64, planner_type="deterministic",
            fallback_used=False, tool_budget=5, tool_calls_used=1, candidate_count=0,
        )
        db.add(vr)
        db.commit()
        state = {"n": 0}

        def flaky_run(db, **kwargs):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("simulated verification failure")
            return {"verification_run_id": vr.id, "status": "completed"}, False

        monkeypatch.setattr(sup_mod, "run_verification", flaky_run)
        from app.services.engineering_supervisor_service import run_supervisor

        result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                   review_run_id=run_id, actor_user_id=d["user"],
                                   use_deepseek=False, max_verification_tool_calls=5,
                                   max_step_retries=1, generate_report=False)
        ver_steps = [s for s in result["steps"] if s["node_name"] == "verification"]
        assert len(ver_steps) == 2
        assert ver_steps[0]["attempt_number"] == 1
        assert ver_steps[0]["status"] == "failed"
        assert ver_steps[0]["error_code"] == "VERIFICATION_RETRYABLE_FAILURE"
        assert ver_steps[1]["attempt_number"] == 2
        assert ver_steps[1]["status"] == "success"
        assert ver_steps[1]["retry_of_id"] == ver_steps[0]["id"]
        assert result["status"] == "ready_to_report"
        db.close()

    def test_mcp_unresolved_needs_human(self, sup_env, monkeypatch):
        """Verification 以 completed_with_warnings 返回且 mcp_context.errors 非空 → needs_human。"""
        import app.services.engineering_supervisor_service as sup_mod

        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        # 真实 VerificationRun 行（FK 引用必须有对应记录）
        vr = ReviewVerificationRun(
            workspace_id=d["workspace"], owner_user_id=d["user"], review_run_id=run_id,
            status="completed_with_warnings", input_state_hash="a" * 64,
            planner_type="deterministic", fallback_used=False,
            tool_budget=5, tool_calls_used=1, candidate_count=0, warning_count=1,
        )
        db.add(vr)
        db.commit()

        def fake_run_verification(db, **kwargs):
            return {
                "verification_run_id": vr.id,
                "status": "completed_with_warnings",
                "plan": {"mcp_context": {"errors": ["engineering_mcp_unavailable"]}},
            }, False

        monkeypatch.setattr(sup_mod, "run_verification", fake_run_verification)
        from app.services.engineering_supervisor_service import run_supervisor

        result, _ = run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                                   review_run_id=run_id, actor_user_id=d["user"],
                                   use_deepseek=False, max_verification_tool_calls=5,
                                   max_step_retries=1, generate_report=False)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "verification"
        assert result["error_code"] == "VERIFICATION_MCP_FAILED"
        ver_failed = [s for s in result["steps"] if s["node_name"] == "verification"][0]
        assert ver_failed["error_code"] == "VERIFICATION_MCP_FAILED"
        db.close()


# ── Reporting 失败边界 ──────────────────────────────────────────────


class TestReportingFailure:
    def test_reporting_failure_no_front_rerun(self, sup_env, monkeypatch):
        """Reporting 失败只标记 needs_human，不重跑前置步骤、不生成报告。"""
        import app.services.engineering_supervisor_service as sup_mod
        from app.services.review_report_service import ReviewReportError

        db = _open_db(sup_env)

        def broken_report(db, **kwargs):
            raise ReviewReportError("REVIEW_REPORT_GENERATION_ERROR", "disk full")

        monkeypatch.setattr(sup_mod, "generate_review_report", broken_report)
        result, _ = _run_supervisor(db, sup_env, generate_report=True)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "reporting"
        assert result["error_code"] == "REPORTING_FAILED"
        assert result["report_id"] is None
        nodes = [s["node_name"] for s in result["steps"]]
        assert nodes.count("extraction") == 1
        assert nodes.count("verification") == 1
        assert nodes.count("quality_review") == 1
        reporting = [s for s in result["steps"] if s["node_name"] == "reporting"][0]
        assert reporting["status"] == "failed"
        db.close()

    def test_reporting_failure_error_safe(self, sup_env, monkeypatch):
        """Reporting 失败的错误消息不得透传内部异常（含路径等细节）。"""
        import app.services.engineering_supervisor_service as sup_mod
        from app.services.review_report_service import ReviewReportError

        db = _open_db(sup_env)

        def leaking_report(db, **kwargs):
            raise ReviewReportError(
                "REVIEW_REPORT_GENERATION_ERROR", r"C:\secret\reports\leak.md 写入失败")

        monkeypatch.setattr(sup_mod, "generate_review_report", leaking_report)
        result, _ = _run_supervisor(db, sup_env, generate_report=True)
        text = json.dumps(result, ensure_ascii=False)
        assert "C:\\secret" not in text and "leak.md" not in text
        assert result["error_message"] == "报告生成失败，请检查后重试"
        db.close()


# ── 前置守卫与故障边界 ─────────────────────────────────────────────


class TestGuards:
    def test_review_run_not_completed(self, sup_env):
        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        run = db.scalar(select(ReviewRun).where(ReviewRun.id == run_id))
        run.status = "pending"
        db.commit()
        from app.services.engineering_supervisor_service import (
            SupervisorServiceError, run_supervisor,
        )

        with pytest.raises(SupervisorServiceError) as excinfo:
            run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                           review_run_id=run_id, actor_user_id=d["user"],
                           use_deepseek=False, max_verification_tool_calls=5,
                           max_step_retries=1, generate_report=False)
        assert excinfo.value.code == "SUPERVISOR_RUN_NOT_COMPLETED"
        db.close()

    def test_supervisor_internal_error_marks_failed(self, sup_env, monkeypatch):
        """内部异常 → run 标记 failed + 固定安全文案，不泄露堆栈。"""
        import app.services.engineering_supervisor_service as sup_mod

        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)

        def boom(db, supervisor, run, findings, evidences, actor_user_id):
            raise RuntimeError("secret internal detail C:\\leak")

        monkeypatch.setattr(sup_mod, "_run_extraction_readiness", boom)
        from app.services.engineering_supervisor_service import (
            SupervisorServiceError, run_supervisor,
        )

        with pytest.raises(SupervisorServiceError) as excinfo:
            run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                           review_run_id=run_id, actor_user_id=d["user"],
                           use_deepseek=False, max_verification_tool_calls=5,
                           max_step_retries=1, generate_report=False)
        assert excinfo.value.code == "SUPERVISOR_INTERNAL_ERROR"
        assert excinfo.value.status_code == 500
        supervisor = db.scalar(
            select(ReviewSupervisorRun)
            .where(ReviewSupervisorRun.review_run_id == run_id)
            .order_by(ReviewSupervisorRun.id.desc())
        )
        assert supervisor.status == "failed"
        assert supervisor.error_message == "Supervisor 执行失败"
        assert "C:\\leak" not in supervisor.error_message
        db.close()

    def test_commit_failure_rollback(self, sup_env, monkeypatch):
        """状态机中途 commit 失败 → 转换为基础失败并标记 failed，不伪装成功。"""
        from sqlalchemy.exc import OperationalError

        from app.services.engineering_supervisor_service import (
            SupervisorServiceError, run_supervisor,
        )

        db = _open_db(sup_env)
        d = sup_env["data"]
        run_id = _fresh_run(db, d)
        real_commit = db.commit
        state = {"n": 0}

        def flaky_commit():
            state["n"] += 1
            if state["n"] == 3:  # extraction Step 写入后的 commit 模拟磁盘故障
                raise OperationalError("sqlite", {}, Exception("simulated disk failure"))
            return real_commit()

        monkeypatch.setattr(db, "commit", flaky_commit)
        with pytest.raises(SupervisorServiceError) as excinfo:
            run_supervisor(db, workspace_id=d["workspace"], owner_user_id=d["user"],
                           review_run_id=run_id, actor_user_id=d["user"],
                           use_deepseek=False, max_verification_tool_calls=5,
                           max_step_retries=1, generate_report=False)
        assert excinfo.value.code == "SUPERVISOR_INTERNAL_ERROR"
        supervisor = db.scalar(
            select(ReviewSupervisorRun)
            .where(ReviewSupervisorRun.review_run_id == run_id)
            .order_by(ReviewSupervisorRun.id.desc())
        )
        assert supervisor.status == "failed"
        assert supervisor.completed_at is not None
        assert db.query(ReviewReport).filter(ReviewReport.review_run_id == run_id).count() == 0
        db.close()

    def test_extraction_information_missing_clarification(self, tmp_path):
        """材料角色确认不齐 → extraction readiness 失败 → needs_human + 结构化 clarification。"""
        from app.db.base import Base as _B

        db_path = tmp_path / "extraction-gap.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        data = _build_db(db_url, tmp_path / "up")
        eng = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk2(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        _B.metadata.create_all(eng)
        S2 = sessionmaker(bind=eng, autoflush=False, autocommit=False)
        db2 = S2()
        wf = db2.scalar(select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == data["workspace"],
            WorkspaceFile.user_confirmed_role == "tender_requirement",
        ))
        db2.delete(wf)
        db2.commit()
        run_id = _fresh_run(db2, data)
        from app.services.engineering_supervisor_service import run_supervisor

        result, _ = run_supervisor(db2, workspace_id=data["workspace"], owner_user_id=data["user"],
                                   review_run_id=run_id, actor_user_id=data["user"],
                                   use_deepseek=False, max_verification_tool_calls=5,
                                   max_step_retries=1, generate_report=True)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "extraction"
        assert result["clarification"]["code"] == "EXTRACTION_INFORMATION_MISSING"
        assert any("tender_requirement" in issue for issue in result["clarification"]["issues"])
        assert result["report_id"] is None
        db2.close(); eng.dispose()


class TestExtractionProfile:
    """Extraction 必须验证 ready Profile：五类必要角色需满足
    user_confirmed_role + FileProfile ready + confirmed_role 一致 + File 归属。
    全部使用独立临时 DB，不污染共享 sup_env。"""

    @staticmethod
    def _setup(tmp_path, mutate):
        from app.db.base import Base as _B

        db_path = tmp_path / "profile.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        data = _build_db(db_url, tmp_path / "up")
        # 独立环境：upload_dir 指向临时目录（路径安全检查必需）、
        # 禁用 MCP（不连接 sup_env 的 server）、FakeEmbedding 索引隔离
        original_upload = settings.upload_dir
        original_mcp = settings.engineering_mcp_enabled
        object.__setattr__(settings, "upload_dir", str(tmp_path / "up"))
        object.__setattr__(settings, "engineering_mcp_enabled", False)
        import app.services.engineering_retrieval_service as svc_mod
        from app.retrieval.embedding import FakeEmbeddingProvider

        idx_root = tmp_path / "idx"
        idx_root.mkdir(parents=True, exist_ok=True)
        original_root = svc_mod._INDEX_ROOT
        original_provider = svc_mod.LocalEmbeddingProvider
        svc_mod._INDEX_ROOT = idx_root
        svc_mod.LocalEmbeddingProvider = lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42)
        try:
            eng = create_engine(db_url, connect_args={"check_same_thread": False})

            @event.listens_for(eng, "connect")
            def _fk2(conn, _r):  # noqa: ARG001
                conn.execute("PRAGMA foreign_keys=ON")

            _B.metadata.create_all(eng)
            S2 = sessionmaker(bind=eng, autoflush=False, autocommit=False)
            db2 = S2()
            from app.services.engineering_retrieval_service import rebuild_index

            rebuild_index(db2, data["workspace"], data["user"])
            mutate(db2, data)
            run_id = _fresh_run(db2, data)
            from app.services.engineering_supervisor_service import run_supervisor

            result, _ = run_supervisor(db2, workspace_id=data["workspace"], owner_user_id=data["user"],
                                       review_run_id=run_id, actor_user_id=data["user"],
                                       use_deepseek=False, max_verification_tool_calls=5,
                                       max_step_retries=1, generate_report=True)
            db2.close(); eng.dispose()
            return result
        finally:
            svc_mod._INDEX_ROOT = original_root
            svc_mod.LocalEmbeddingProvider = original_provider
            object.__setattr__(settings, "upload_dir", original_upload)
            object.__setattr__(settings, "engineering_mcp_enabled", original_mcp)

    @staticmethod
    def _role_profile(db2, data, role="tender_requirement"):
        from app.models.file_profile import FileProfile

        return db2.scalar(select(FileProfile).where(
            FileProfile.workspace_id == data["workspace"],
            FileProfile.confirmed_role == role,
        ))

    def test_profile_not_ready_blocked(self, tmp_path):
        def mutate(db2, data):
            self._role_profile(db2, data).status = "profiling"

        result = self._setup(tmp_path, mutate)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "extraction"
        assert result["clarification"]["code"] == "EXTRACTION_INFORMATION_MISSING"
        assert any("Profile 未就绪" in issue for issue in result["clarification"]["issues"])
        assert result["report_id"] is None

    def test_profile_failed_blocked(self, tmp_path):
        def mutate(db2, data):
            self._role_profile(db2, data).status = "failed"

        result = self._setup(tmp_path, mutate)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "extraction"
        assert any("Profile 未就绪" in issue for issue in result["clarification"]["issues"])

    def test_profile_confirmed_role_mismatch_blocked(self, tmp_path):
        def mutate(db2, data):
            self._role_profile(db2, data).confirmed_role = "bid_response"

        result = self._setup(tmp_path, mutate)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "extraction"
        assert any("角色确认不一致" in issue for issue in result["clarification"]["issues"])

    def test_profile_missing_blocked(self, tmp_path):
        from app.models.file_profile import FileProfile

        def mutate(db2, data):
            profile = self._role_profile(db2, data)
            db2.delete(profile)
            db2.commit()

        result = self._setup(tmp_path, mutate)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "extraction"
        assert any("缺少 Profile" in issue for issue in result["clarification"]["issues"])

    def test_duplicate_role_blocked(self, tmp_path):
        """同一必要角色出现重复文件记录 → 阻断，不能由重复记录冒充完成。"""
        def mutate(db2, data):
            from app.models.file import File
            from app.models.workspace_file import WorkspaceFile

            dup = Path(settings.upload_dir) / "dup.md"
            dup.write_text("重复角色材料", encoding="utf-8")
            fl = File(owner_user_id=data["user"], filename="dup.md", file_type="markdown",
                      file_path=str(dup), status="ready")
            db2.add(fl)
            db2.commit()
            wf2 = WorkspaceFile(workspace_id=data["workspace"], file_id=fl.id,
                                user_confirmed_role="tender_requirement")
            db2.add(wf2)
            db2.commit()

        result = self._setup(tmp_path, mutate)
        assert result["status"] == "needs_human"
        assert result["current_step"] == "extraction"
        assert any("重复文件" in issue for issue in result["clarification"]["issues"])

    def test_all_roles_ready_passes(self, tmp_path):
        """五种角色全部 ready 且一致 → extraction 通过，gate 通过并生成报告。"""
        result = self._setup(tmp_path, lambda db2, data: None)
        assert result["status"] == "completed"
        assert result["current_step"] == "reporting"
        assert result["quality_gate"]["status"] == "passed"

    def test_extraction_profile_error_no_path_leak(self, tmp_path):
        """extraction 阻断的澄清信息不得泄露路径或内部异常。"""

        def mutate(db2, data):
            self._role_profile(db2, data).status = "profiling"

        result = self._setup(tmp_path, mutate)
        text = json.dumps(result, ensure_ascii=False)
        for forbidden in ("C:\\", "D:\\", "Users", "Traceback", "File ", "uploads", "leak.db"):
            assert forbidden not in text, f"泄露: {forbidden}"
        assert result["error_code"] in (None, "EXTRACTION_INFORMATION_MISSING")


# ── 隔离与安全 ─────────────────────────────────────────────────────


class TestIsolationAndSafety:
    def test_workspace_delete_cascade(self, sup_env, tmp_path):
        """独立临时 DB 验证级联（不污染共享 sup_env DB）。"""
        from app.db.base import Base as _B

        db_path = tmp_path / "cascade.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        data = _build_db(db_url, tmp_path / "up")
        eng = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk2(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        _B.metadata.create_all(eng)
        S2 = sessionmaker(bind=eng, autoflush=False, autocommit=False)
        db2 = S2()
        run_id = _fresh_run(db2, data)
        from app.services.engineering_supervisor_service import run_supervisor
        run_supervisor(db2, workspace_id=data["workspace"], owner_user_id=data["user"],
                       review_run_id=run_id, actor_user_id=data["user"],
                       use_deepseek=False, max_verification_tool_calls=5,
                       max_step_retries=1, generate_report=False)
        ws = db2.scalar(select(Workspace).where(Workspace.id == data["workspace"]))
        db2.delete(ws)
        db2.commit()
        assert db2.query(ReviewSupervisorRun).count() == 0
        assert db2.query(ReviewSupervisorStep).count() == 0
        db2.close(); eng.dispose()

    def test_finding_evidence_unchanged(self, sup_env):
        db = _open_db(sup_env)
        _run_supervisor(db, sup_env, generate_report=True)
        for f in db.scalars(select(ReviewFinding)).all():
            assert f.status == "pending_review"
        assert db.query(Evidence).count() >= 1
        db.close()

    def test_history_report_unchanged(self, sup_env):
        db = _open_db(sup_env)
        _run_supervisor(db, sup_env, generate_report=True)
        reports = list(db.scalars(select(ReviewReport)).all())
        assert len(reports) >= 1
        versions = [r.version for r in reports]
        assert versions == sorted(versions)
        db.close()

    def test_error_no_path_or_token(self, sup_env, monkeypatch):
        from app.mcp.review_tools_client import ReviewToolsMCPClient as _C
        from app.mcp.errors import unavailable as _unavail

        db = _open_db(sup_env)
        monkeypatch.setattr(_C, "call_tool_sync",
                            lambda self, t, a: (_ for _ in ()).throw(_unavail()))
        result, _ = _run_supervisor(db, sup_env, generate_report=False, max_step_retries=0)
        text = json.dumps(result, ensure_ascii=False)
        for forbidden in ("C:\\", "D:\\", "Users", "Traceback", "File ", ".env",
                          sup_env["secret"]):
            assert forbidden not in text, f"泄露: {forbidden}"
        db.close()

    def test_general_no_entry(self):
        from app.api.v2 import engineering_reviews as mod

        assert mod.router.prefix == "/api/v2/workspaces/{workspace_id}"

    def test_history_report_assets_sha_unchanged(self, sup_env):
        """历史报告资产 SHA 必须保持不变（Supervisor 只新增报告，不修改历史资产）。"""
        db = _open_db(sup_env)
        before = {a.content_hash for a in db.scalars(select(ReviewReportAsset)).all()}
        _run_supervisor(db, sup_env, generate_report=True)
        after = {a.content_hash for a in db.scalars(select(ReviewReportAsset)).all()}
        assert before.issubset(after)
        db.close()

    def test_default_app_db_not_polluted(self, sup_env):
        """专项测试不得触碰默认 app.db；运行一次 Supervisor 后默认库文件保持原样。"""
        backend_dir = Path(__file__).resolve().parents[1]
        default_db = backend_dir / "data" / "app.db"
        assert "app.db" not in settings.database_url.lower()
        before = (
            (default_db.stat().st_size, default_db.stat().st_mtime_ns)
            if default_db.exists() else None
        )
        _run_supervisor(db := _open_db(sup_env), sup_env, generate_report=True)
        db.close()
        after = (
            (default_db.stat().st_size, default_db.stat().st_mtime_ns)
            if default_db.exists() else None
        )
        assert before == after, "默认 app.db 被测试改动"
