"""V3 阶段 2B-2 最终收尾补修 — 真实 API 闭环 + 逐条 Evidence + 失败注入 + 快照完整性"""

from __future__ import annotations
import json, re, time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.evidence import Evidence
from app.models.user import User
from app.core.config import settings as _s
from app.services.security_service import hash_password as _hp

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "examples" / "engineering_review_v1" / "golden_case"
BRIEF_DATA = json.loads((GOLDEN_DIR / "review_brief.json").read_text(encoding="utf-8"))
PASSWORD = "SafePassword!2026"
ROLE_MAP = {
    "01_合成招标要求.pdf": "tender_requirement", "02_合成投标响应.pdf": "bid_response",
    "03_人员设备清单.xlsx": "personnel_equipment_data", "04_合成资质附件.pdf": "qualification_attachment",
    "05_项目澄清.md": "clarification_document",
}
GOLDEN_FILES = list(ROLE_MAP.keys())

# ── fixtures ──────────────────────────────────────────────────────
@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def _fk(c, _r): c.execute("PRAGMA foreign_keys=ON")  # noqa: ARG001
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()
    try: yield db
    finally: db.rollback(); db.close(); Base.metadata.drop_all(engine); engine.dispose()

@pytest.fixture
def client(db_session):
    S = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    def _ov():
        db = S()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = _ov
    with TestClient(app) as c: yield c
    app.dependency_overrides.clear()

# ── helpers ───────────────────────────────────────────────────────
def _add_user(db_session, username):
    u = User(username=username, password_hash=_hp(PASSWORD), role="user", status="active", must_change_password=False)
    db_session.add(u); db_session.commit(); return u

def _session_csrf(c): return {_s.csrf_header_name: c.cookies.get(_s.csrf_cookie_name)}

def _login(c, username):
    assert c.get("/api/v2/auth/csrf").status_code == 200
    return c.post("/api/v2/auth/login", headers={_s.csrf_header_name: c.cookies.get(_s.csrf_cookie_name)}, json={"username": username, "password": PASSWORD})

def _upload(c, ws_id, fn, h):
    p = GOLDEN_DIR / fn; content = p.read_bytes()
    mime = "application/pdf" if fn.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fn.endswith(".xlsx") else "text/markdown"
    r = c.post(f"/api/v2/workspaces/{ws_id}/files", headers=h, files={"file": (fn, content, mime)})
    assert r.status_code == 201, f"upload {fn}: {r.status_code} {r.text}"; return r.json()

def _understand(c, ws_id, fid, h):
    r = c.post(f"/api/v2/workspaces/{ws_id}/files/{fid}/understand", json={"use_deepseek": False, "run_ocr": False}, headers=h)
    assert r.status_code in (200, 201), f"understand {fid}: {r.status_code}"

def _confirm_role(c, ws_id, fid, role, h):
    r = c.patch(f"/api/v2/workspaces/{ws_id}/files/{fid}/profile", json={"confirmed_role": role}, headers=h)
    assert r.status_code == 200, f"confirm {role}: {r.status_code} {r.text}"
    d = r.json(); assert d.get("confirmed_role") == role or d.get("effective_role") == role

def _setup_full(c, ws_id, h):
    for fn in GOLDEN_FILES:
        up = _upload(c, ws_id, fn, h); _understand(c, ws_id, up["file_id"], h)
    r = c.get(f"/api/v2/workspaces/{ws_id}/files", headers=h)
    for f_rec in r.json():
        fn = f_rec["display_name"]
        if fn in ROLE_MAP: _confirm_role(c, ws_id, f_rec["file_id"], ROLE_MAP[fn], h)

def _brief_confirm(c, ws_id, h):
    r = c.post(f"/api/v2/workspaces/{ws_id}/review-briefs", json={"raw_requirements": "审查", "interpreted": BRIEF_DATA["interpreted"], "interpreter_type": "deterministic_fixture"}, headers=h)
    assert r.status_code == 201; bid = r.json()["id"]
    r = c.post(f"/api/v2/workspaces/{ws_id}/review-briefs/{bid}/confirm", headers=h)
    assert r.status_code == 200; return bid

def _run_execute(c, ws_id, h, bid):
    r = c.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid}, headers=h)
    assert r.status_code == 201; rid = r.json()["id"]
    r = c.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
    return rid, r

def _get_findings(c, ws_id, rid, h):
    r = c.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/findings", headers=h)
    assert r.status_code == 200
    return {f["issue_code"]: f for f in r.json()}

def _get_evidences(c, ws_id, rid, h):
    r = c.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/evidences", headers=h)
    assert r.status_code == 200
    return {e["id"]: e for e in r.json()}

def _eng_ws(c, h):
    r = c.post("/api/v2/workspaces", json={"name": "测试", "workspace_type": "engineering"}, headers=h)
    assert r.status_code == 201; return r.json()["id"]

# ── 核心闭环 ──────────────────────────────────────────────────────
class TestCorePipeline:
    def test_full_api_loop(self, client, db_session):
        _add_user(db_session, "core"); assert _login(client, "core").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        rid, r = _run_execute(client, ws_id, h, bid)
        assert r.status_code == 200 and r.json()["finding_count"] == 12
        assert len(r.json()["passed_rule_ids"]) == 2
        assert "SYN-DOC-001" in r.json()["passed_rule_ids"]

    def test_template_auto_set(self, client, db_session):
        _add_user(db_session, "tpl"); assert _login(client, "tpl").status_code == 200
        h = _session_csrf(client)
        r = client.post("/api/v2/workspaces", json={"name": "E", "workspace_type": "engineering"}, headers=h)
        assert r.json().get("review_template_key") == "engineering_bid_review_v1"
        r = client.post("/api/v2/workspaces", json={"name": "G", "workspace_type": "general"}, headers=h)
        assert r.json().get("review_template_key") is None

# ── 反硬编码 ──────────────────────────────────────────────────────
class TestAntiHardcoding:
    def test_diff_leader(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人：张三", ["项目负责人", "负责人"]) == "张三"

    def test_diff_cert(self):
        from app.services.engineering_review_pipeline_service import _find_cert_number
        assert _find_cert_number("证书编号：CMA-TEST-2025-001") == "CMA-TEST-2025-001"

    def test_cert_value_on_next_line(self):
        from app.services.engineering_review_pipeline_service import _find_cert_number
        assert _find_cert_number("证书编号\nABC-JC-98765") == "ABC-JC-98765"

    def test_cert_value_precedes_rule_reference(self):
        from app.services.engineering_review_pipeline_service import _find_cert_number
        text = "证书编号\nSYN-JC-24018\nSYN-EQ-002 对照值"
        assert _find_cert_number(text) == "SYN-JC-24018"

    def test_rule_code_without_label_is_not_cert(self):
        from app.services.engineering_review_pipeline_service import _find_cert_number
        assert _find_cert_number("正文仅包含规则代码 SYN-EQ-002") is None

    def test_rule_reference_after_label_is_not_cert(self):
        from app.services.engineering_review_pipeline_service import _find_cert_number
        assert _find_cert_number("证书编号\nSYN-EQ-002 对照值") is None

    def test_missing_cert_none(self):
        from app.services.engineering_review_pipeline_service import _find_cert_number
        assert _find_cert_number("无证书") is None

    def test_diff_price(self):
        from app.services.engineering_review_pipeline_service import _find_price
        assert _find_price("总报价：1,850,000 元") == 1850000

    def test_diff_date(self):
        from app.services.engineering_review_pipeline_service import _find_related_date
        assert _find_related_date("签署：2025-03-15\n提交：2025-04-01", ["签署", "提交"]) == "2025-03-15"

    def test_nonempty_not_forced(self):
        from app.services.engineering_review_pipeline_service import _find_label_value
        assert _find_label_value("项目名称：真实项目", ["项目名称"]) == "真实项目"

    def test_empty_marker(self):
        from app.services.engineering_review_pipeline_service import _find_label_value
        assert _find_label_value("项目名称：留空", ["项目名称"]) == "留空"

    def test_no_golden_in_code(self):
        code = (Path(__file__).resolve().parents[1] / "app" / "services" / "engineering_review_pipeline_service.py").read_text(encoding="utf-8")
        for kw in ["SYN-JC-24018", "林海", "2026-10-02", "2027-06-30", "SYN-CMA-2026-014"]:
            assert kw not in code, f"硬编码: {kw!r}"

    # ── 负责人姓名解析专项（阶段 3B-1 补修）────────────────────────
    def test_leader_colon_cn(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人：张三", ["项目负责人", "负责人"]) == "张三"

    def test_leader_colon_en(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人: 李四", ["项目负责人", "负责人"]) == "李四"

    def test_leader_cross_line(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人\n王五\n虚构姓名", ["项目负责人", "负责人"]) == "王五"

    def test_leader_natural_language(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人为赵六，证书编号 ABC-JC-98765", ["项目负责人", "负责人"]) == "赵六"

    def test_leader_no_label_but_cert(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("证书编号\nSYN-JC-24018", ["项目负责人", "负责人"]) is None

    def test_leader_next_line_is_cert(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人\nSYN-JC-24018", ["项目负责人", "负责人"]) is None

    def test_leader_next_line_is_rule_code(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人\nSYN-EQ-002 对照值", ["项目负责人", "负责人"]) is None

    def test_leader_next_line_is_field_label(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人\n证书编号", ["项目负责人", "负责人"]) is None

    def test_leader_golden_pdf(self):
        """使用真实黄金 PDF 文本抽取，必须得到林海。"""
        import fitz
        from app.services.engineering_review_pipeline_service import _find_person_name
        doc = fitz.open(GOLDEN_DIR / "02_合成投标响应.pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        result = _find_person_name(text, ["项目负责人", "负责人", "负责人姓名"])
        assert result == "林海", f"期望林海，实际得到 {result!r}"

    def test_leader_equals_sign(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人 = 孙七", ["项目负责人", "负责人"]) == "孙七"

    def test_leader_space_only(self):
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人 周八", ["项目负责人", "负责人"]) == "周八"

    def test_leader_description_not_name(self):
        """标签后的整段说明不应被识别为姓名。"""
        from app.services.engineering_review_pipeline_service import _find_person_name
        assert _find_person_name("项目负责人\n需要具备相关资质证书", ["项目负责人", "负责人"]) is None

# ── 逐条 Evidence 定位 ────────────────────────────────────────────
EXPECTED_EVIDENCE = {
    "SYN-REQ-001": {"locator_type": "pdf_page", "page_number": 1},
    "SYN-REQ-002": {"locator_type": "spreadsheet_cell", "sheet_name": "人员清单", "cell_range": "B3"},
    "SYN-EQ-001": {"locator_type": "spreadsheet_cell", "sheet_name": "项目概况"},
    "SYN-EQ-002": {"locator_type": "spreadsheet_cell", "sheet_name": "人员清单", "cell_range": "D3"},
    "SYN-NUM-001": {"locator_type": "spreadsheet_cell", "sheet_name": "人员清单", "cell_range": "B8"},
    "SYN-NUM-002": {"locator_type": "pdf_page", "page_number": 1},
    "SYN-NUM-003": {"locator_type": "spreadsheet_cell", "sheet_name": "设备清单", "cell_range": "D7"},
    "SYN-DATE-001": {"locator_type": "pdf_page", "page_number": 1},
    "SYN-DATE-002": {"locator_type": "pdf_page", "page_number": 1},
    "SYN-DATE-003": {"locator_type": "spreadsheet_cell", "sheet_name": "设备清单", "cell_range": "F4"},
    "SYN-EVD-001": {"locator_type": "spreadsheet_cell", "sheet_name": "人员清单", "cell_range": "B3", "forbidden_page": 2},
    "SYN-EVD-002": {"locator_type": "pdf_page", "page_number": 2, "forbidden_sheet": "人员清单"},
}

class TestPerFindingEvidence:
    def test_each_finding_evidence(self, client, db_session):
        _add_user(db_session, "ev_each"); assert _login(client, "ev_each").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        rid, r = _run_execute(client, ws_id, h, bid)
        assert r.status_code == 200

        findings = _get_findings(client, ws_id, rid, h)
        evidences = _get_evidences(client, ws_id, rid, h)
        assert len(findings) == 12

        for evidence in evidences.values():
            assert evidence["parser_name"]
            assert evidence["parser_version"]
            stored = db_session.get(Evidence, evidence["id"])
            assert stored is not None
            assert evidence["parser_name"] == stored.parser_name
            assert evidence["parser_version"] == stored.parser_version

        for code, exp in EXPECTED_EVIDENCE.items():
            f = findings[code]
            assert len(f["evidence_ids"]) >= 1, f"{code}: 无 evidence"
            found_match = False
            for eid in f["evidence_ids"]:
                if eid not in evidences: continue
                ev = evidences[eid]
                match = True
                if "locator_type" in exp and ev["locator_type"] != exp["locator_type"]: match = False
                if "page_number" in exp and ev.get("page_number") != exp["page_number"]: match = False
                if "sheet_name" in exp and ev.get("sheet_name") != exp["sheet_name"]: match = False
                if "cell_range" in exp and ev.get("cell_range") != exp["cell_range"]: match = False
                if "forbidden_page" in exp and ev.get("page_number") == exp["forbidden_page"]: match = False
                if "forbidden_sheet" in exp and ev.get("sheet_name") == exp["forbidden_sheet"]: match = False
                if match: found_match = True; break
            assert found_match, f"{code}: 未找到匹配 Evidence，期望 {exp}"

    def test_cross_file_has_both_sides(self, client, db_session):
        """交叉文件规则应绑定双方来源。"""
        _add_user(db_session, "ev_xfile"); assert _login(client, "ev_xfile").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        rid, r = _run_execute(client, ws_id, h, bid)

        findings = _get_findings(client, ws_id, rid, h)
        evidences = _get_evidences(client, ws_id, rid, h)
        files = client.get(f"/api/v2/workspaces/{ws_id}/files", headers=h).json()
        bid_file_id = next(
            item["file_id"] for item in files
            if item["display_name"] == "02_合成投标响应.pdf"
        )
        # 两条跨文件规则都必须同时绑定 PDF 与 spreadsheet 双方来源。
        for issue_code in ("SYN-EQ-001", "SYN-EQ-002"):
            f = findings[issue_code]
            evs = [evidences[eid] for eid in f["evidence_ids"] if eid in evidences]
            types = {e["locator_type"] for e in evs}
            assert "pdf_page" in types, f"{issue_code} 缺少 PDF Evidence: {types}"
            assert "spreadsheet_cell" in types, f"{issue_code} 缺少 spreadsheet Evidence: {types}"

        eq2_evidences = [evidences[eid] for eid in findings["SYN-EQ-002"]["evidence_ids"]]
        pdf_evidence = next(e for e in eq2_evidences if e["locator_type"] == "pdf_page")
        excel_evidence = next(e for e in eq2_evidences if e["locator_type"] == "spreadsheet_cell")
        assert pdf_evidence["file_id"] == bid_file_id
        assert pdf_evidence["page_number"] == 1
        assert pdf_evidence["quote"] == "证书编号：SYN-JC-24018"
        assert excel_evidence["sheet_name"] == "人员清单"
        assert excel_evidence["cell_range"] == "D3"

# ── 幂等 ──────────────────────────────────────────────────────────
class TestIdempotent:
    def test_ids_unchanged(self, client, db_session):
        _add_user(db_session, "idem"); assert _login(client, "idem").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid}, headers=h)
        rid = r.json()["id"]

        r1 = client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
        assert r1.status_code == 200; fc1, ec1 = r1.json()["finding_count"], r1.json()["evidence_count"]
        fids1 = {f["id"] for f in client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/findings", headers=h).json()}
        eids1 = {e["id"] for e in client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/evidences", headers=h).json()}

        r2 = client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
        assert r2.status_code == 200; assert r2.json()["finding_count"] == fc1; assert r2.json()["evidence_count"] == ec1
        fids2 = {f["id"] for f in client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/findings", headers=h).json()}
        eids2 = {e["id"] for e in client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/evidences", headers=h).json()}
        assert fids1 == fids2; assert eids1 == eids2

# ── 错误码 ────────────────────────────────────────────────────────
class TestErrorCodes:
    def test_material_missing(self, client, db_session):
        _add_user(db_session, "ec1"); assert _login(client, "ec1").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        bid = _brief_confirm(client, ws_id, h)  # no files uploaded
        rid, r = _run_execute(client, ws_id, h, bid)
        assert r.status_code == 422 and r.json()["detail"]["error_code"] == "REVIEW_MATERIAL_MISSING"
        assert client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}", headers=h).json()["status"] == "failed"

    def test_role_duplicated(self, client, db_session):
        _add_user(db_session, "ec2"); assert _login(client, "ec2").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        for fn in GOLDEN_FILES:
            up = _upload(client, ws_id, fn, h); _understand(client, ws_id, up["file_id"], h)
        r = client.get(f"/api/v2/workspaces/{ws_id}/files", headers=h)
        fids = [f["file_id"] for f in r.json()]
        _confirm_role(client, ws_id, fids[0], "tender_requirement", h)
        _confirm_role(client, ws_id, fids[1], "tender_requirement", h)  # dup
        for i in range(2, 5):
            _confirm_role(client, ws_id, fids[i], list(ROLE_MAP.values())[i], h)
        bid = _brief_confirm(client, ws_id, h)
        rid, r = _run_execute(client, ws_id, h, bid)
        assert r.status_code == 422
        assert r.json()["detail"]["error_code"] in ("REVIEW_ROLE_DUPLICATED", "REVIEW_MATERIAL_MISSING")
        assert client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}", headers=h).json()["status"] == "failed"

# ── 失败注入 ──────────────────────────────────────────────────────
class TestFailureInjection:
    def test_evidence_failure_fails_run(self, client, db_session, monkeypatch):
        """Evidence 创建异常时 Run 为 failed，错误码正确。"""
        _add_user(db_session, "fi_ev"); assert _login(client, "fi_ev").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid}, headers=h)
        rid = r.json()["id"]

        from app.services.engineering_review_pipeline_service import _persist_evidence as _orig
        def _fail(*a, **kw): raise RuntimeError("injected evidence failure")
        monkeypatch.setattr("app.services.engineering_review_pipeline_service._persist_evidence", _fail)

        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
        assert r.status_code == 422
        assert r.json()["detail"]["error_code"] == "REVIEW_EVIDENCE_ERROR"
        rd = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}", headers=h).json()
        assert rd["status"] == "failed"

    def test_finding_failure_fails_run(self, client, db_session, monkeypatch):
        """Finding 创建异常时 Run 为 failed，不会被标记 completed。"""
        _add_user(db_session, "fi_fd"); assert _login(client, "fi_fd").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid}, headers=h)
        rid = r.json()["id"]

        from app.services.engineering_review_pipeline_service import create_review_finding as _orig
        def _fail(*a, **kw): raise RuntimeError("injected finding failure")
        monkeypatch.setattr("app.services.engineering_review_pipeline_service.create_review_finding", _fail)

        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
        assert r.status_code in (422, 500)
        rd = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}", headers=h).json()
        assert rd["status"] == "failed"

# ── 快照完整性 ────────────────────────────────────────────────────
class TestSnapshotIntegrity:
    def test_tampered_snapshot_fails_with_code(self, client, db_session):
        _add_user(db_session, "snap"); assert _login(client, "snap").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid}, headers=h)
        rid = r.json()["id"]

        from app.models.review_run import ReviewRun
        run = db_session.query(ReviewRun).filter(ReviewRun.id == rid).first()
        run.rule_snapshot_json = "corrupted"; db_session.commit()

        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
        assert r.status_code == 422
        rd = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}", headers=h).json()
        assert rd["status"] == "failed"
        # 详情应暴露完整性错误
        ie = rd.get("integrity_error")
        assert ie is not None, "应包含 integrity_error"
        assert ie.get("error_code") == "REVIEW_SNAPSHOT_INTEGRITY_ERROR"
        # passed_rule_ids 应为空（不来自磁盘 YAML）
        assert rd["passed_rule_ids"] == []

    def test_superseded_brief_ok(self, client, db_session):
        _add_user(db_session, "super"); assert _login(client, "super").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid1 = _brief_confirm(client, ws_id, h)
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid1}, headers=h)
        rid = r.json()["id"]
        bid2 = _brief_confirm(client, ws_id, h)  # supersedes bid1
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
        assert r.status_code == 200 and r.json()["finding_count"] == 12

# ── 隔离 ──────────────────────────────────────────────────────────
class TestIsolation:
    def test_cross_workspace(self, client, db_session):
        u = _add_user(db_session, "iso_ws"); assert _login(client, "iso_ws").status_code == 200
        h = _session_csrf(client)
        wa = client.post("/api/v2/workspaces", json={"name": "A", "workspace_type": "engineering"}, headers=h).json()["id"]
        wb = client.post("/api/v2/workspaces", json={"name": "B", "workspace_type": "engineering"}, headers=h).json()["id"]
        _setup_full(client, wa, h); bid = _brief_confirm(client, wa, h)
        r = client.post(f"/api/v2/workspaces/{wa}/review-runs", json={"review_brief_id": bid}, headers=h)
        rid = r.json()["id"]; client.post(f"/api/v2/workspaces/{wa}/review-runs/{rid}/execute", headers=h)
        fids = [f["id"] for f in client.get(f"/api/v2/workspaces/{wa}/review-runs/{rid}/findings", headers=h).json()]
        # B URL can't touch A resources
        for path in [f"/review-briefs/{bid}/confirm", f"/review-runs/{rid}", f"/review-runs/{rid}/findings",
                     f"/review-runs/{rid}/evidences", f"/review-runs/{rid}/execute"]:
            assert client.post(f"/api/v2/workspaces/{wb}{path}", headers=h).status_code == 404 if "confirm" in path or "execute" in path else client.get(f"/api/v2/workspaces/{wb}{path}", headers=h).status_code == 404
        assert client.post(f"/api/v2/workspaces/{wb}/review-findings/{fids[0]}/actions", json={"action_type": "confirm"}, headers=h).status_code == 404

    def test_cross_user(self, client, db_session):
        alice = _add_user(db_session, "alice_iso"); bob = _add_user(db_session, "bob_iso")
        assert _login(client, "alice_iso").status_code == 200; ah = _session_csrf(client)
        ws_id = _eng_ws(client, ah); _setup_full(client, ws_id, ah); bid = _brief_confirm(client, ws_id, ah)
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid}, headers=ah)
        rid = r.json()["id"]; client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=ah)
        fids = [f["id"] for f in client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/findings", headers=ah).json()]
        client.cookies.clear(); assert _login(client, "bob_iso").status_code == 200; bh = _session_csrf(client)
        for path in [f"/review-briefs/{bid}", f"/review-briefs/current", f"/review-runs/{rid}",
                     f"/review-runs/{rid}/findings", f"/review-runs/{rid}/evidences"]:
            assert client.get(f"/api/v2/workspaces/{ws_id}{path}", headers=bh).status_code == 404
        assert client.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=bh).status_code == 404
        assert client.post(f"/api/v2/workspaces/{ws_id}/review-findings/{fids[0]}/actions", json={"action_type": "confirm"}, headers=bh).status_code == 404

# ── Brief 响应 + Action ────────────────────────────────────────────
class TestBriefAndActions:
    def test_brief_has_interpreted(self, client, db_session):
        _add_user(db_session, "br"); assert _login(client, "br").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        r = client.post(f"/api/v2/workspaces/{ws_id}/review-briefs", json={
            "raw_requirements": "检查", "interpreted": BRIEF_DATA["interpreted"], "interpreter_type": "deterministic_fixture"}, headers=h)
        d = r.json()
        assert d["raw_requirements"] == "检查" and d["interpreted"] is not None and "objectives" in d["interpreted"]

    def test_actions(self, client, db_session):
        _add_user(db_session, "act"); assert _login(client, "act").status_code == 200
        h = _session_csrf(client); ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h); bid = _brief_confirm(client, ws_id, h)
        rid, _ = _run_execute(client, ws_id, h, bid)
        fs = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/findings", headers=h).json()
        a = fs[0]["id"]; b = fs[1]["id"]; c = fs[2]["id"]; d = fs[3]["id"]
        assert client.post(f"/api/v2/workspaces/{ws_id}/review-findings/{a}/actions", json={"action_type": "confirm"}, headers=h).json()["finding"]["status"] == "confirmed"
        assert client.post(f"/api/v2/workspaces/{ws_id}/review-findings/{b}/actions", json={"action_type": "reject"}, headers=h).json()["finding"]["status"] == "rejected"
        mr = client.post(f"/api/v2/workspaces/{ws_id}/review-findings/{c}/actions", json={"action_type": "modify", "modified_conclusion": "新"}, headers=h)
        assert mr.json()["finding"]["status"] == "modified" and mr.json()["action"]["before_json"] is not None
        assert client.post(f"/api/v2/workspaces/{ws_id}/review-findings/{d}/actions", json={"action_type": "resolve"}, headers=h).json()["finding"]["status"] == "resolved"
        assert len(client.get(f"/api/v2/workspaces/{ws_id}/review-findings/{a}/actions", headers=h).json()) >= 1

# ── 质量门 ────────────────────────────────────────────────────────
class TestQualityGate:
    def test_no_direct_db_entity_creation(self):
        code = Path(__file__).read_text(encoding="utf-8")
        # 用正则精确匹配构造调用，不先替换代码
        assert re.search(r'^\s*\w+\s*=\s*File\(', code, re.MULTILINE) is None, "不应直接创建 File 实例"
        assert re.search(r'^\s*\w+\s*=\s*WorkspaceFile\(', code, re.MULTILINE) is None, "不应直接创建 WorkspaceFile 实例"
        assert re.search(r'^\s*\w+\s*=\s*FileProfile\(', code, re.MULTILINE) is None, "不应直接创建 FileProfile 实例"
        # review_template_key 赋值不应出现在测试中
        assert re.search(r'review_template_key\s*=\s*', code.replace(
            "assert re.search(r'review_template_key", "SKIP"), re.MULTILINE) is None, "不应直接设置 review_template_key"
