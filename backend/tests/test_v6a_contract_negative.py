"""阶段 6A 契约专项负面测试（离线，不访问公网，不加载真实 BGE/DeepSeek）。

覆盖指令要求的两类契约修复负面场景：
- Evidence 哈希语义冲突：来源完整性字段 + 复算/文件哈希/locator/chunk 校验；
- input snapshot 契约：pipeline 自动持久化、哈希校验、篡改阻断；
- validation split：映射稳定、validation 指标非空；
- 评测脚本源码不存在手工写 DB 的绕过代码。

测试使用真实黄金案例文件（临时副本），构造隔离 SQLite；
不写默认 app.db/uploads/reports/retrieval；无递归删除。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_brief import ReviewBrief
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.review_supervisor_run import ReviewSupervisorRun
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.models.file_profile import FileProfile
from app.services.evidence_provenance import (
    CORPUS_CHUNK,
    FIELD_LOCATOR,
    compute_file_sha256_safe,
)
from app.services.review_engine_service import _compute_evidence_hash
from app.services.security_service import hash_password

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
CASE_DIR = REPO_ROOT / "examples" / "engineering_review_v1" / "golden_case"
QUERY_PATH = CASE_DIR / "retrieval_queries.json"

ROLES = ("tender_requirement", "bid_response", "personnel_equipment_data",
         "qualification_attachment", "clarification_document")
ROLE_FILES = {
    "tender_requirement": "01_合成招标要求.pdf",
    "bid_response": "02_合成投标响应.pdf",
    "personnel_equipment_data": "03_人员设备清单.xlsx",
    "qualification_attachment": "04_合成资质附件.pdf",
    "clarification_document": "05_项目澄清.md",
}


def _snapshot_for(fields_paths: list[str]) -> tuple[str, str]:
    """构造与 pipeline 相同风格的规范 input snapshot（json, hash）。"""
    fields = {p: {"value": "x", "evidence_ids": []} for p in fields_paths}
    payload = {"fields": fields, "document_roles": {}}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"))
    return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def eng_env(tmp_path_factory):
    """真实黄金案例文件 + 完整工程环境（无 MCP server，无索引）。"""
    tmp_root = tmp_path_factory.mktemp("v6a_contract")
    db_path = tmp_root / "contract.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    upload_dir = tmp_root / "uploads"
    upload_dir.mkdir(parents=True)
    original_upload = settings.upload_dir
    object.__setattr__(settings, "upload_dir", str(upload_dir))
    try:
        engine = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = S()
        u = User(username="v6a_contract", password_hash=hash_password("SafePassword!2026"),
                 role="user", status="active", must_change_password=False)
        db.add(u); db.commit()
        ws = Workspace(owner_user_id=u.id, name="6A 契约", workspace_type="engineering",
                       review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws); db.commit()
        file_ids = {}
        for role in ROLES:
            src = CASE_DIR / ROLE_FILES[role]
            suffix = src.suffix
            ftype = {"pdf": "pdf", "xlsx": "xlsx", "md": "markdown"}[suffix.lstrip(".")]
            dst = upload_dir / f"f_{role}{suffix}"
            dst.write_bytes(src.read_bytes())
            fl = File(owner_user_id=u.id, filename=ROLE_FILES[role], file_type=ftype,
                      file_path=str(dst), status="ready")
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

        from app.services.review_rule_service import (
            compute_rule_pack_hash,
            compute_rule_snapshot,
            load_rule_pack,
        )

        rule_pack = load_rule_pack("engineering_bid_review_v1")
        snap = compute_rule_snapshot(rule_pack)
        data = {
            "user": u.id, "workspace": ws.id, "file_ids": file_ids, "brief": brief.id,
            "rule_snapshot": snap, "rule_pack_hash": compute_rule_pack_hash(snap),
            "rule_version": {r.rule_id: r.version for r in rule_pack.rules},
            "upload_dir": upload_dir, "db_url": db_url,
        }
        db.close()
        engine.dispose()
        yield data
    finally:
        object.__setattr__(settings, "upload_dir", original_upload)


def _open_db(eng_env):
    engine = create_engine(eng_env["db_url"], connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return S()


def _new_run(db, eng_env, *, with_input_snapshot=True):
    d = eng_env
    brief_snap = json.dumps({"id": d["brief"], "version": 1, "content_hash": "a" * 64,
                             "raw_requirements": "审查", "interpreted_json": "{}"})
    run = ReviewRun(workspace_id=d["workspace"], owner_user_id=d["user"],
                    review_template_key="engineering_bid_review_v1", status="pending",
                    rule_pack_id="engineering_bid_review_v1", rule_pack_version="1.1.0",
                    rule_pack_hash=d["rule_pack_hash"], rule_snapshot_json=d["rule_snapshot"],
                    review_brief_id=d["brief"], review_brief_version=1,
                    review_brief_hash=hashlib.sha256(brief_snap.encode()).hexdigest(),
                    review_brief_snapshot_json=brief_snap)
    if with_input_snapshot:
        snap_json, snap_hash = _snapshot_for(
            ["personnel_equipment_data.total_personnel"])
        run.input_snapshot_json = snap_json
        run.input_snapshot_hash = snap_hash
    db.add(run); db.commit()
    db.refresh(run)
    return run


def _new_supervisor(db, run, eng_env):
    sup = ReviewSupervisorRun(workspace_id=run.workspace_id, owner_user_id=run.owner_user_id,
                              review_run_id=run.id, status="running",
                              input_state_hash="a" * 64, graph_version="5b.1",
                              quality_gate_version="2.0", max_step_retries=1,
                              retry_count=0, started_at=None)
    db.add(sup); db.commit()
    db.refresh(sup)
    return sup


def _mk_evidence(
    db, run, eng_env, *,
    locator_type: str,
    role: str,
    page_number: int | None = None,
    sheet_name: str | None = None,
    cell_range: str | None = None,
    chunk_id: int | None = None,
    quote: str = "Q",
    provenance_type: str | None = FIELD_LOCATOR,
    source_file_hash: str | None = None,
    source_chunk_id: str | None = None,
    source_chunk_hash: str | None = None,
) -> Evidence:
    file_id = eng_env["file_ids"][role]
    if source_file_hash is None:
        file_path = Path(eng_env["upload_dir"]) / f"f_{role}{Path(ROLE_FILES[role]).suffix}"
        source_file_hash = compute_file_sha256_safe(str(file_path))
    data = {
        "file_id": file_id, "locator_type": locator_type,
        "page_number": page_number, "sheet_name": sheet_name,
        "cell_range": cell_range, "chunk_id": chunk_id, "quote": quote,
    }
    ev = Evidence(review_run_id=run.id, workspace_id=run.workspace_id,
                  owner_user_id=run.owner_user_id, file_id=file_id,
                  locator_type=locator_type, page_number=page_number,
                  sheet_name=sheet_name, cell_range=cell_range, chunk_id=chunk_id,
                  quote=quote, content_hash=_compute_evidence_hash(data),
                  provenance_type=provenance_type,
                  source_file_hash=source_file_hash,
                  source_chunk_id=source_chunk_id,
                  source_chunk_hash=source_chunk_hash,
                  parser_name="p", parser_version="1")
    db.add(ev); db.commit(); db.refresh(ev)
    return ev


def _mk_finding(db, run, ev: Evidence, eng_env, rule_id="SYN-NUM-001"):
    f = ReviewFinding(review_run_id=run.id, workspace_id=run.workspace_id,
                      owner_user_id=run.owner_user_id, issue_code=rule_id,
                      title=rule_id, category="numeric_threshold", severity="high",
                      conclusion="c", suggestion="s", rule_id=rule_id,
                      rule_version=eng_env["rule_version"][rule_id],
                      evidence_ids_json=json.dumps([ev.id]),
                      status="pending_review", source_step_id=f"engine:{rule_id}")
    db.add(f); db.commit(); db.refresh(f)
    return f


def _run_gate(db, run, sup, eng_env):
    from app.services.engineering_supervisor_service import _run_quality_gate

    findings = list(db.scalars(select(ReviewFinding).where(
        ReviewFinding.review_run_id == run.id)).all())
    evidences = list(db.scalars(select(Evidence).where(
        Evidence.review_run_id == run.id)).all())
    return _run_quality_gate(db, sup, run, findings, evidences, eng_env["user"])


# ── 1. 未变化的 pipeline Evidence 通过（含 snapshot 自动持久化）──────────


class TestPipelineFresh:
    def test_pipeline_evidence_fresh_passes_gate(self, eng_env):
        """真实黄金案例 pipeline → 全部 Evidence 带来源字段 → Gate passed。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env, with_input_snapshot=False)
        from app.services.engineering_review_pipeline_service import run_engineering_review

        result = run_engineering_review(db, run=run,
                                        workspace=db.scalar(select(Workspace).where(
                                            Workspace.id == eng_env["workspace"])),
                                        owner_user_id=eng_env["user"])
        assert result["status"] == "completed"
        evidences = list(db.scalars(select(Evidence).where(
            Evidence.review_run_id == run.id)).all())
        assert evidences
        for ev in evidences:
            assert ev.provenance_type == FIELD_LOCATOR
            assert ev.source_file_hash and len(ev.source_file_hash) == 64
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert gate["status"] == "passed", gate["errors"]
        assert "EVIDENCE_STALE" not in gate["errors"]
        assert "EVIDENCE_PROVENANCE_MISSING" not in gate["errors"]
        assert "INPUT_SNAPSHOT_MISMATCH" not in gate["errors"]
        db.close()

    def test_input_snapshot_auto_persisted(self, eng_env):
        """pipeline 自动持久化 input_snapshot_json/hash，JSON 与哈希一致。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env, with_input_snapshot=False)
        from app.services.engineering_review_pipeline_service import run_engineering_review

        run_engineering_review(db, run=run,
                               workspace=db.scalar(select(Workspace).where(
                                   Workspace.id == eng_env["workspace"])),
                               owner_user_id=eng_env["user"])
        db.refresh(run)
        assert run.input_snapshot_json and run.input_snapshot_hash
        assert (hashlib.sha256(run.input_snapshot_json.encode("utf-8")).hexdigest()
                == run.input_snapshot_hash)
        snap = json.loads(run.input_snapshot_json)
        assert "fields" in snap and "document_roles" in snap
        assert "bid_response.project_name" in snap["fields"]
        db.close()

    def test_chunk_id_zero_legal_in_pipeline_and_gate(self, eng_env):
        """text_chunk 0-based：pipeline 澄清证据 chunk_id=0 且 Gate 放行。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env, with_input_snapshot=False)
        from app.services.engineering_review_pipeline_service import run_engineering_review

        run_engineering_review(db, run=run,
                               workspace=db.scalar(select(Workspace).where(
                                   Workspace.id == eng_env["workspace"])),
                               owner_user_id=eng_env["user"])
        clar_ev = db.scalar(select(Evidence).where(
            Evidence.review_run_id == run.id,
            Evidence.file_id == eng_env["file_ids"]["clarification_document"]))
        assert clar_ev is not None
        assert clar_ev.chunk_id == 0
        assert clar_ev.provenance_type == FIELD_LOCATOR
        # 单独构造 chunk_id=0 的 finding 走 Gate → fresh
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert gate["status"] == "passed", gate["errors"]
        db.close()


# ── 2-9. EVIDENCE_STALE / EVIDENCE_PROVENANCE_MISSING 负面场景 ──────────


class TestEvidenceStale:
    def test_source_file_changed_stale(self, eng_env):
        """来源文件内容变化 → EVIDENCE_STALE。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=1)
        bid_path = Path(eng_env["upload_dir"]) / "f_bid_response.pdf"
        original = bid_path.read_bytes()
        bid_path.write_bytes(original + b"tampered")
        try:
            f = _mk_finding(db, run, ev, eng_env)
            sup = _new_supervisor(db, run, eng_env)
            gate = _run_gate(db, run, sup, eng_env)
            assert "EVIDENCE_STALE" in gate["errors"]
            stale_msgs = [c["safe_message"] for c in gate["checks"]
                          if c["check_code"] == "EVIDENCE_STALE"]
            assert stale_msgs and "来源文件内容已变化" in stale_msgs[0]
        finally:
            bid_path.write_bytes(original)
        db.close()

    def test_pdf_page_missing_stale(self, eng_env):
        """PDF page 消失（page 超出当前页数）→ EVIDENCE_STALE。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=99)
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "EVIDENCE_STALE" in gate["errors"]
        db.close()

    def test_excel_sheet_missing_stale(self, eng_env):
        """Excel sheet 消失 → EVIDENCE_STALE。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="spreadsheet_cell",
                          role="personnel_equipment_data", sheet_name="不存在的表",
                          cell_range="B3")
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "EVIDENCE_STALE" in gate["errors"]
        db.close()

    def test_text_chunk_missing_stale(self, eng_env):
        """text chunk 消失（chunk_id 超出当前块数）→ EVIDENCE_STALE。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="text_chunk",
                          role="clarification_document", chunk_id=99)
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "EVIDENCE_STALE" in gate["errors"]
        db.close()

    def test_corpus_chunk_hash_changed_stale(self, eng_env):
        """corpus 候选 chunk hash 变化 → EVIDENCE_STALE。"""
        db = _open_db(eng_env)
        from app.services.engineering_retrieval_service import build_workspace_corpus

        chunks, _w = build_workspace_corpus(db, eng_env["workspace"], eng_env["user"])
        md_chunk = next(c for c in chunks
                        if c.file_id == eng_env["file_ids"]["clarification_document"])
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="text_chunk",
                          role="clarification_document", chunk_id=0,
                          provenance_type=CORPUS_CHUNK,
                          source_chunk_id=md_chunk.chunk_id,
                          source_chunk_hash="0" * 64)
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "EVIDENCE_STALE" in gate["errors"]
        stale_msgs = [c["safe_message"] for c in gate["checks"]
                      if c["check_code"] == "EVIDENCE_STALE"]
        assert stale_msgs and "来源文本块哈希不一致" in stale_msgs[0]
        db.close()

    def test_corpus_chunk_valid_passes(self, eng_env):
        """corpus_chunk provenance 正确时 Gate 放行（对照：不是一律 fresh 也非一律 stale）。"""
        db = _open_db(eng_env)
        from app.services.engineering_retrieval_service import build_workspace_corpus

        chunks, _w = build_workspace_corpus(db, eng_env["workspace"], eng_env["user"])
        md_chunk = next(c for c in chunks
                        if c.file_id == eng_env["file_ids"]["clarification_document"])
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="text_chunk",
                          role="clarification_document", chunk_id=0,
                          provenance_type=CORPUS_CHUNK,
                          source_chunk_id=md_chunk.chunk_id,
                          source_chunk_hash=md_chunk.content_hash)
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert gate["status"] == "passed", gate["errors"]
        db.close()

    def test_evidence_content_hash_tampered_stale(self, eng_env):
        """Evidence.content_hash 被篡改（记录哈希复算不一致）→ EVIDENCE_STALE。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=1)
        ev.content_hash = "f" * 64
        db.commit()
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "EVIDENCE_STALE" in gate["errors"]
        stale_msgs = [c["safe_message"] for c in gate["checks"]
                      if c["check_code"] == "EVIDENCE_STALE"]
        assert stale_msgs and "证据记录哈希不一致" in stale_msgs[0]
        db.close()

    def test_source_file_hash_tampered_stale(self, eng_env):
        """source_file_hash 被篡改 → EVIDENCE_STALE。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=1)
        ev.source_file_hash = "e" * 64
        db.commit()
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "EVIDENCE_STALE" in gate["errors"]
        db.close()

    def test_historical_evidence_missing_provenance(self, eng_env):
        """历史 Evidence 缺来源字段 → 独立稳定错误 EVIDENCE_PROVENANCE_MISSING。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=1, provenance_type=None, source_file_hash=None)
        f = _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert gate["status"] == "failed"
        assert "EVIDENCE_PROVENANCE_MISSING" in gate["errors"]
        assert "EVIDENCE_STALE" not in gate["errors"]
        # 禁止静默放行：该 finding 进入 need_more_info，且其文件不计入 related_file_ids
        assert f.id in gate["need_more_information_finding_ids"]
        assert ev.file_id not in gate["related_file_ids"]
        db.close()

    def test_stale_error_no_path_leak(self, eng_env):
        """stale 错误消息不得泄露磁盘路径。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=99)
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        text = json.dumps(gate, ensure_ascii=False)
        for forbidden in ("C:\\", "D:\\", "Users", "Traceback", "uploads", "f_bid_response"):
            assert forbidden not in text, f"泄露: {forbidden}"
        db.close()


# ── 12. input snapshot 篡改阻断 ────────────────────────────────────────


class TestInputSnapshot:
    def test_snapshot_hash_mismatch_blocked(self, eng_env):
        """input_snapshot_hash 与 JSON 不一致 → INPUT_SNAPSHOT_MISMATCH 阻断。"""
        db = _open_db(eng_env)
        run = _new_run(db, eng_env)
        run.input_snapshot_json = run.input_snapshot_json + " "
        db.commit()
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=1)
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "INPUT_SNAPSHOT_MISMATCH" in gate["errors"]
        assert gate["status"] == "failed"
        db.close()

    def test_snapshot_missing_required_field_blocked(self, eng_env):
        """快照存在且哈希一致但缺少规则必需字段 → INPUT_SNAPSHOT_MISMATCH。"""
        db = _open_db(eng_env)
        snap_json, snap_hash = _snapshot_for(["无关字段"])
        run = _new_run(db, eng_env, with_input_snapshot=False)
        run.input_snapshot_json = snap_json
        run.input_snapshot_hash = snap_hash
        db.commit()
        ev = _mk_evidence(db, run, eng_env, locator_type="pdf_page", role="bid_response",
                          page_number=1)
        _mk_finding(db, run, ev, eng_env)
        sup = _new_supervisor(db, run, eng_env)
        gate = _run_gate(db, run, sup, eng_env)
        assert "INPUT_SNAPSHOT_MISMATCH" in gate["errors"]
        db.close()


# ── 13-15. split 映射与评测脚本契约 ───────────────────────────────────


class TestSplitContract:
    def test_split_mapping_stable_and_matches_freeze(self, eng_env):
        """映射稳定：冻结与 runner 计算结果一致，SHA 匹配，重复生成逐字节一致。"""
        from app.evaluation.v4_end_to_end_runner import (
            compute_evaluation_split_mapping,
            freeze_engineering_review_v1,
            split_mapping_document,
        )

        freeze = freeze_engineering_review_v1(CASE_DIR, REPO_ROOT)
        queries_raw = json.loads(QUERY_PATH.read_text(encoding="utf-8"))["queries"]
        m1 = compute_evaluation_split_mapping(queries_raw)
        m2 = compute_evaluation_split_mapping(queries_raw)
        assert split_mapping_document(m1) == split_mapping_document(m2)
        sm = freeze["split_mapping"]
        assert sm["sha256"] == hashlib.sha256(
            split_mapping_document(m1).encode("utf-8")).hexdigest()
        assert freeze["splits"] == {"development": 20, "validation": 8, "test": 16}
        assert sm["development_query_ids"] == sorted(
            q for q in m1 if m1[q] == "development")
        assert sm["validation_query_ids"] == sorted(
            q for q in m1 if m1[q] == "validation")

    def test_validation_metrics_not_empty(self, eng_env):
        """validation 指标非空：8 条查询可执行且聚合非空。"""
        from app.evaluation.v4_end_to_end_runner import (
            collect_retrieval_eval,
            compute_evaluation_split_mapping,
        )
        from app.evaluation.v4_metrics import aggregate_retrieval
        from app.evaluation.v3_embedding import FakeEmbeddingProvider

        fake = FakeEmbeddingProvider(dimension=512, seed=42)
        result = collect_retrieval_eval(
            CASE_DIR, QUERY_PATH,
            encode_query=lambda texts: fake.encode_passages(texts), top_k=5,
        )
        queries_raw = json.loads(QUERY_PATH.read_text(encoding="utf-8"))["queries"]
        mapping = compute_evaluation_split_mapping(queries_raw)
        per_a = [q for q in result.per_query_answerable
                 if mapping.get(q["query_id"]) == "validation"]
        per_n = [q for q in result.per_query_no_answer
                 if mapping.get(q["query_id"]) == "validation"]
        agg = aggregate_retrieval(per_a, per_n)
        assert agg["answerable"]["answerable_count"] == 7
        assert agg["no_answer"]["no_answer_count"] == 1
        assert agg["answerable"]["recall@3_mean"] is not None
        assert agg["no_answer"]["false_positive_rate"] is not None


class TestEvalScriptNoBypass:
    EVAL_SCRIPTS = (
        REPO_ROOT / "scripts" / "verify_stage6a_real_evaluation.py",
        REPO_ROOT / "scripts" / "verify_stage6a_retry_evaluation.py",
    )

    def test_eval_scripts_do_not_write_input_snapshot(self):
        """真实评测脚本源码不存在手工写 ReviewRun snapshot 字段的赋值。"""
        import re

        for path in self.EVAL_SCRIPTS:
            src = path.read_text(encoding="utf-8")
            for pattern in (
                r"input_snapshot_hash\s*=",
                r"input_snapshot_json\s*=",
                r"\.input_snapshot_hash",
                r"\.input_snapshot_json",
            ):
                hits = [ln for ln in src.splitlines() if re.search(pattern, ln)]
                for hit in hits:
                    # 只读断言（哈希校验）允许出现，赋值禁止
                    assert not re.match(r"\s*[a-zA-Z_][\w.]*\s*\.\s*input_snapshot", hit), (
                        f"{path.name} 存在手工写 input snapshot 的绕过代码: {hit.strip()}")

    def test_eval_scripts_do_not_bypass_quality_gate(self):
        """评测脚本不得无条件返回 gate fresh、删除 hash 比较或模拟 gate。"""
        src = (REPO_ROOT / "scripts" / "verify_stage6a_real_evaluation.py").read_text(
            encoding="utf-8")
        assert "input_snapshot_hash = hashlib" not in src  # 不再手工填充哈希
        assert "gate" in src  # 脚本确实断言 gate passed
        assert "gate passed" in src or "gate.get" in src
