"""阶段 4C-3：候选证据人工采纳闭环测试。

覆盖：候选来源边界、accept/reject、幂等与冲突、服务端重新校验（篡改/stale）、
     事务原子性、报告不可变、隔离、级联删除、迁移 roundtrip、默认目录零污染。

普通 pytest：
- Fake Embedding（monkeypatch LocalEmbeddingProvider），禁止联网和真实模型加载
- 独立临时数据库、上传目录和索引目录
- 默认 app.db / uploads / retrieval 零变化
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings as _s
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.evidence import Evidence
from app.models.review_candidate_decision import ReviewCandidateDecision
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_report_asset import ReviewReportAsset
from app.models.review_tool_call import ReviewToolCall
from app.models.review_verification_run import ReviewVerificationRun
from app.models.user import User
from app.retrieval.embedding import FakeEmbeddingProvider
from app.services.security_service import hash_password as _hp

GOLDEN_DIR = (
    Path(__file__).resolve().parents[2]
    / "examples" / "engineering_review_v1" / "golden_case"
)
BRIEF_DATA = json.loads((GOLDEN_DIR / "review_brief.json").read_text(encoding="utf-8"))
PASSWORD = "SafePassword!2026"
ROLE_MAP = {
    "01_合成招标要求.pdf": "tender_requirement",
    "02_合成投标响应.pdf": "bid_response",
    "03_人员设备清单.xlsx": "personnel_equipment_data",
    "04_合成资质附件.pdf": "qualification_attachment",
    "05_项目澄清.md": "clarification_document",
}
GOLDEN_FILES = list(ROLE_MAP.keys())
BACKEND_DIR = Path(__file__).resolve().parents[1]


# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session):
    S = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)

    def _ov():
        db = S()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _ov
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """隔离上传目录 + 索引目录（不触碰默认 storage）。"""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    original_upload = _s.upload_dir
    object.__setattr__(_s, "upload_dir", str(upload_dir))

    idx_root = tmp_path / "retrieval" / "workspaces"
    idx_root.mkdir(parents=True, exist_ok=True)
    import app.services.engineering_retrieval_service as svc_mod
    monkeypatch.setattr(svc_mod, "_INDEX_ROOT", idx_root, raising=True)

    def _make_fake(**kw):
        return FakeEmbeddingProvider(dimension=512, seed=42)

    monkeypatch.setattr(
        "app.services.engineering_retrieval_service.LocalEmbeddingProvider",
        _make_fake,
    )
    try:
        yield
    finally:
        object.__setattr__(_s, "upload_dir", original_upload)


# ── helpers（与 4C-2 测试同一模式） ────────────────────────────────


def _add_user(db_session, username: str) -> User:
    u = User(
        username=username,
        password_hash=_hp(PASSWORD),
        role="user",
        status="active",
        must_change_password=False,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _session_csrf(c) -> dict:
    return {_s.csrf_header_name: c.cookies.get(_s.csrf_cookie_name)}


def _login(c, username: str):
    assert c.get("/api/v2/auth/csrf").status_code == 200
    r = c.post(
        "/api/v2/auth/login",
        headers=_session_csrf(c),
        json={"username": username, "password": PASSWORD},
    )
    assert r.status_code == 200
    return r


def _upload(c, ws_id, fn, h):
    p = GOLDEN_DIR / fn
    mime = (
        "application/pdf" if fn.endswith(".pdf")
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fn.endswith(".xlsx")
        else "text/markdown"
    )
    r = c.post(
        f"/api/v2/workspaces/{ws_id}/files",
        headers=h,
        files={"file": (fn, p.read_bytes(), mime)},
    )
    assert r.status_code == 201, f"upload {fn}: {r.status_code} {r.text}"
    return r.json()


def _understand(c, ws_id, fid, h):
    r = c.post(
        f"/api/v2/workspaces/{ws_id}/files/{fid}/understand",
        json={"use_deepseek": False, "run_ocr": False},
        headers=h,
    )
    assert r.status_code in (200, 201), f"understand {fid}: {r.status_code}"


def _confirm_role(c, ws_id, fid, role, h):
    r = c.patch(
        f"/api/v2/workspaces/{ws_id}/files/{fid}/profile",
        json={"confirmed_role": role},
        headers=h,
    )
    assert r.status_code == 200, f"confirm {role}: {r.status_code} {r.text}"


def _setup_full(c, ws_id, h):
    for fn in GOLDEN_FILES:
        up = _upload(c, ws_id, fn, h)
        _understand(c, ws_id, up["file_id"], h)
    r = c.get(f"/api/v2/workspaces/{ws_id}/files", headers=h)
    for f_rec in r.json():
        if f_rec["display_name"] in ROLE_MAP:
            _confirm_role(c, ws_id, f_rec["file_id"], ROLE_MAP[f_rec["display_name"]], h)


def _brief_confirm(c, ws_id, h) -> int:
    r = c.post(
        f"/api/v2/workspaces/{ws_id}/review-briefs",
        json={
            "raw_requirements": "审查",
            "interpreted": BRIEF_DATA["interpreted"],
            "interpreter_type": "deterministic_fixture",
        },
        headers=h,
    )
    assert r.status_code == 201
    bid = r.json()["id"]
    r = c.post(f"/api/v2/workspaces/{ws_id}/review-briefs/{bid}/confirm", headers=h)
    assert r.status_code == 200
    return bid


def _run_execute(c, ws_id, h, bid) -> int:
    r = c.post(f"/api/v2/workspaces/{ws_id}/review-runs", json={"review_brief_id": bid}, headers=h)
    assert r.status_code == 201
    rid = r.json()["id"]
    r = c.post(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/execute", headers=h)
    assert r.status_code == 200, f"execute: {r.status_code} {r.text}"
    return rid


def _eng_ws(c, h, name="测试工程") -> int:
    r = c.post(
        "/api/v2/workspaces",
        json={"name": name, "workspace_type": "engineering"},
        headers=h,
    )
    assert r.status_code == 201
    return r.json()["id"]


def _full_ready(c, db_session, username: str = "user4c3") -> tuple[int, dict, int]:
    _add_user(db_session, username)
    assert _login(c, username).status_code == 200
    h = _session_csrf(c)
    ws_id = _eng_ws(c, h)
    _setup_full(c, ws_id, h)
    bid = _brief_confirm(c, ws_id, h)
    rid = _run_execute(c, ws_id, h, bid)
    return ws_id, h, rid


def _findings_map(c, ws_id, rid, h) -> dict[str, dict]:
    r = c.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/findings", headers=h)
    assert r.status_code == 200
    return {f["issue_code"]: f for f in r.json()}


def _build_index(c, ws_id, h, rebuild=False):
    r = c.post(
        f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index",
        headers=h,
        json={"rebuild": rebuild},
    )
    assert r.status_code == 200, f"index: {r.status_code} {r.text}"


def _post_verification(c, ws_id, rid, h, **payload) -> tuple[int, dict]:
    body = {"use_deepseek": False, "max_tool_calls": 5}
    body.update(payload)
    r = c.post(
        f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs",
        headers=h,
        json=body,
    )
    return r.status_code, r.json()


def _candidates(c, ws_id, rid, vrid, h) -> dict:
    r = c.get(
        f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs/{vrid}/candidates",
        headers=h,
    )
    assert r.status_code == 200, f"candidates: {r.status_code} {r.text}"
    return r.json()


def _decide(c, ws_id, rid, vrid, h, tool_call_id, rank, decision, note=None):
    body = {"tool_call_id": tool_call_id, "candidate_rank": rank, "decision": decision}
    if note is not None:
        body["review_note"] = note
    r = c.post(
        f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs/{vrid}/candidate-decisions",
        headers=h,
        json=body,
    )
    return r.status_code, r.json()


def _decisions(c, ws_id, rid, vrid, h) -> list[dict]:
    r = c.get(
        f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs/{vrid}/candidate-decisions",
        headers=h,
    )
    assert r.status_code == 200
    return r.json()


def _evidences(c, ws_id, rid, h) -> list[dict]:
    r = c.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/evidences", headers=h)
    assert r.status_code == 200
    return r.json()


def _verification_with_candidates(c, db_session, h=None, ws_id=None, rid=None):
    """建索引 + 确定性 Verification，返回 (vrid, candidates[])。"""
    _build_index(c, ws_id, h)
    code, data = _post_verification(c, ws_id, rid, h)
    assert code == 201, data
    vrid = data["verification_run_id"]
    payload = _candidates(c, ws_id, rid, vrid, h)
    assert payload["candidates"], "应存在候选证据"
    return vrid, payload["candidates"]


def _pick(candidates, locator_type=None, exclude=()):
    for cand in candidates:
        key = (cand["tool_call_id"], cand["candidate_rank"])
        if key in exclude:
            continue
        if locator_type and cand["locator_type"] != locator_type:
            continue
        return cand
    return None


# ── 1-3. 候选来源边界 ─────────────────────────────────────────────


class TestCandidateSource:
    def test_candidates_only_from_successful_retrieval(self, client, db_session):
        """候选只来自成功 retrieval ToolCall，字段契约完整。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        success_hybrid_ids = {
            t.id
            for t in db_session.scalars(select(ReviewToolCall)).all()
            if t.status == "success" and t.tool_name == "engineering_hybrid_retrieval"
        }
        assert candidates
        required_fields = {
            "verification_run_id", "tool_call_id", "finding_id", "issue_code",
            "candidate_rank", "chunk_id", "file_id", "file_name", "file_role",
            "locator_type", "page_number", "sheet_name", "cell_range", "quote",
            "score", "bm25_rank", "dense_rank", "content_hash", "parser_name",
            "parser_version", "index_sha256", "corpus_sha256",
            "candidate_only", "requires_human_confirmation",
            "decision", "evidence_id", "review_note",
        }
        for cand in candidates:
            assert cand["tool_call_id"] in success_hybrid_ids
            assert cand["candidate_only"] is True
            assert cand["requires_human_confirmation"] is True
            assert required_fields.issubset(set(cand)), set(cand)
            assert cand["decision"] is None  # 未决策
        # 同一 ToolCall 内候选顺序稳定（rank 递增）
        by_call: dict[int, list[int]] = {}
        for cand in candidates:
            by_call.setdefault(cand["tool_call_id"], []).append(cand["candidate_rank"])
        for ranks in by_call.values():
            assert ranks == sorted(ranks)
            assert len(ranks) == len(set(ranks)), "同一 ToolCall 内 rank 唯一"

    def test_prepare_and_failed_attempt_produce_no_candidates(self, client, db_session):
        """prepare 与失败 attempt 不产生候选。"""
        ws_id, h, rid = _full_ready(client, db_session)
        # 不建索引 → INDEX_MISSING → prepare → retry
        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        vrid = data["verification_run_id"]
        payload = _candidates(client, ws_id, rid, vrid, h)
        excluded_ids = {
            t.id
            for t in db_session.scalars(select(ReviewToolCall)).all()
            if t.status != "success"
            or t.tool_name == "engineering_retrieval_index_prepare"
        }
        assert excluded_ids, "应存在失败 attempt 或 prepare 调用"
        for cand in payload["candidates"]:
            assert cand["tool_call_id"] not in excluded_ids

    def test_retry_success_candidates_source(self, client, db_session):
        """retry 成功产生的候选来自 attempt_number=2 的调用。"""
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h)  # 无索引 → 必走 retry
        assert code == 201
        vrid = data["verification_run_id"]
        payload = _candidates(client, ws_id, rid, vrid, h)
        assert payload["candidates"]
        retry_ids = {
            t.id
            for t in db_session.scalars(select(ReviewToolCall)).all()
            if t.attempt_number == 2 and t.status == "success"
        }
        assert retry_ids, "应存在成功的 retry 调用"
        assert any(
            cand["tool_call_id"] in retry_ids for cand in payload["candidates"]
        ), "retry 成功应产生候选"


# ── 4-11. accept / reject / 幂等 / 原子性 ──────────────────────────


class TestDecisionFlow:
    def test_accept_creates_evidence_and_binds_finding(self, client, db_session):
        """accept 创建正式 Evidence 并追加到正确 Finding（原顺序保留）。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        before_findings = _findings_map(client, ws_id, rid, h)
        before_ids = before_findings[cand["issue_code"]]["evidence_ids"]
        ev_before = len(_evidences(client, ws_id, rid, h))

        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
            note="人工核对后确认相关",
        )
        assert code == 201, data
        assert data["reused"] is False
        assert data["decision"] == "accept"
        assert data["evidence_id"] is not None

        evs = _evidences(client, ws_id, rid, h)
        assert len(evs) == ev_before + 1
        new_ev = next(e for e in evs if e["id"] == data["evidence_id"])
        assert new_ev["file_id"] == cand["file_id"]
        assert new_ev["locator_type"] == cand["locator_type"]

        after = _findings_map(client, ws_id, rid, h)[cand["issue_code"]]
        assert after["evidence_ids"] == before_ids + [data["evidence_id"]]

    def test_reject_creates_no_evidence(self, client, db_session):
        """reject 只写决策，不创建 Evidence、不修改 Finding。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        before = _findings_map(client, ws_id, rid, h)
        ev_before = _evidences(client, ws_id, rid, h)

        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "reject",
            note="与当前问题无关",
        )
        assert code == 201, data
        assert data["evidence_id"] is None
        assert _evidences(client, ws_id, rid, h) == ev_before
        assert _findings_map(client, ws_id, rid, h) == before

    def test_same_decision_idempotent(self, client, db_session):
        """同一决定重复提交：200 + reused=true，不产生重复数据。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        code1, data1 = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code1 == 201
        ev_count = len(_evidences(client, ws_id, rid, h))
        code2, data2 = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code2 == 200, data2
        assert data2["reused"] is True
        assert data2["id"] == data1["id"]
        assert len(_evidences(client, ws_id, rid, h)) == ev_count
        assert len(_decisions(client, ws_id, rid, vrid, h)) == 1

        cand2 = _pick(candidates, exclude={(cand["tool_call_id"], cand["candidate_rank"])})
        code3, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand2["tool_call_id"], cand2["candidate_rank"], "reject",
        )
        assert code3 == 201
        code4, data4 = _decide(
            client, ws_id, rid, vrid, h,
            cand2["tool_call_id"], cand2["candidate_rank"], "reject",
        )
        assert code4 == 200 and data4["reused"] is True

    def test_opposite_decision_conflict(self, client, db_session):
        """已接受再拒绝 / 已拒绝再接受 → 409 冲突。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand1 = _pick(candidates)
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand1["tool_call_id"], cand1["candidate_rank"], "accept",
        )
        assert code == 201
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand1["tool_call_id"], cand1["candidate_rank"], "reject",
        )
        assert code == 409
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_DECISION_CONFLICT"

        cand2 = _pick(candidates, exclude={(cand1["tool_call_id"], cand1["candidate_rank"])})
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand2["tool_call_id"], cand2["candidate_rank"], "reject",
        )
        assert code == 201
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand2["tool_call_id"], cand2["candidate_rank"], "accept",
        )
        assert code == 409
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_DECISION_CONFLICT"

    def test_same_evidence_reused_not_duplicated(self, client, db_session):
        """不同候选定位到同一 chunk 时复用同一 Evidence，不重复创建/绑定。"""
        ws_id, h, rid = _full_ready(client, db_session)
        _build_index(client, ws_id, h)
        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        vrid = data["verification_run_id"]

        # 用真实工具路径为另一条 Finding 再执行一次相同 query 的检索
        # （复用同一 VerificationRun，真实产生第二条 ToolCall）
        from app.agents.engineering_tool_registry import (
            ALLOWED_AGENT_TYPE,
            ENGINEERING_TOOL_HYBRID_RETRIEVAL,
            execute_engineering_tool,
        )

        verification = db_session.scalar(
            select(ReviewVerificationRun).where(ReviewVerificationRun.id == vrid)
        )
        verification.tool_budget = 50  # 测试内放开预算（真实路径仍走预算校验）
        db_session.commit()
        first_call = db_session.scalar(
            select(ReviewToolCall).where(
                ReviewToolCall.verification_run_id == vrid,
                ReviewToolCall.tool_name == ENGINEERING_TOOL_HYBRID_RETRIEVAL,
                ReviewToolCall.status == "success",
            )
        )
        assert first_call is not None
        src_input = json.loads(first_call.input_json)
        other_finding = db_session.scalar(
            select(ReviewFinding).where(
                ReviewFinding.review_run_id == rid,
                ReviewFinding.id != first_call.review_finding_id,
            )
        )
        output2, call2 = execute_engineering_tool(
            db_session,
            agent_type=ALLOWED_AGENT_TYPE,
            tool_name=ENGINEERING_TOOL_HYBRID_RETRIEVAL,
            input_data=src_input,
            verification_run=verification,
            review_run_id=rid,
            review_finding_id=other_finding.id,
            workspace_id=ws_id,
            owner_user_id=verification.owner_user_id,
            node_name="verification",
            attempt_number=1,
        )
        assert output2.get("results"), "第二次检索应有结果"

        payload = _candidates(client, ws_id, rid, vrid, h)
        first_cands = [c for c in payload["candidates"] if c["tool_call_id"] == first_call.id]
        second_cands = [c for c in payload["candidates"] if c["tool_call_id"] == call2.id]
        pair = None
        for a in first_cands:
            for b in second_cands:
                if a["chunk_id"] == b["chunk_id"]:
                    pair = (a, b)
                    break
            if pair:
                break
        assert pair, "两次相同 query 应命中同一 chunk"
        cand_a, cand_b = pair

        ev_before = len(_evidences(client, ws_id, rid, h))
        code, data_a = _decide(
            client, ws_id, rid, vrid, h,
            cand_a["tool_call_id"], cand_a["candidate_rank"], "accept",
        )
        assert code == 201
        code, data_b = _decide(
            client, ws_id, rid, vrid, h,
            cand_b["tool_call_id"], cand_b["candidate_rank"], "accept",
        )
        assert code == 201
        # 同一 Evidence 被复用：只创建一次
        assert data_b["evidence_id"] == data_a["evidence_id"]
        assert len(_evidences(client, ws_id, rid, h)) == ev_before + 1
        # 两条 Finding 各绑定一次，不重复
        findings = list(
            db_session.scalars(
                select(ReviewFinding).where(ReviewFinding.review_run_id == rid)
            ).all()
        )
        for f in findings:
            ids = json.loads(f.evidence_ids_json)
            assert len(ids) == len(set(ids))

    def test_finding_fields_unchanged_after_accept(self, client, db_session):
        """accept 不改变 Finding 的 status/severity/conclusion/suggestion。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        before = _findings_map(client, ws_id, rid, h)
        cand = _pick(candidates)
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 201
        after = _findings_map(client, ws_id, rid, h)
        for issue_code, f_before in before.items():
            f_after = after[issue_code]
            assert f_after["status"] == f_before["status"] == "pending_review"
            assert f_after["severity"] == f_before["severity"]
            assert f_after["conclusion"] == f_before["conclusion"]
            assert f_after["suggestion"] == f_before["suggestion"]

    def test_atomic_rollback_on_evidence_error(self, client, db_session, monkeypatch):
        """Evidence 创建异常 → 整体回滚：无 Evidence、Finding 不变、无决策。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)

        def _boom(*args, **kwargs):
            raise RuntimeError("注入 Evidence 创建失败")

        monkeypatch.setattr(
            "app.services.verification_candidate_service.create_evidence", _boom
        )
        ev_before = _evidences(client, ws_id, rid, h)
        finding_before = _findings_map(client, ws_id, rid, h)

        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 500, data
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_DECISION_ERROR"
        assert _evidences(client, ws_id, rid, h) == ev_before
        assert _findings_map(client, ws_id, rid, h) == finding_before
        assert db_session.scalar(select(ReviewCandidateDecision)) is None

    def test_atomic_rollback_on_commit_failure(self, client, db_session, monkeypatch):
        """最终 commit 失败 → rollback 后三者均无残留。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)

        from sqlalchemy.orm import Session as _Session

        original_commit = _Session.commit

        def _failing_commit(self):
            raise RuntimeError("注入提交失败")

        monkeypatch.setattr(_Session, "commit", _failing_commit)
        ev_before = _evidences(client, ws_id, rid, h)
        finding_before = _findings_map(client, ws_id, rid, h)
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        monkeypatch.setattr(_Session, "commit", original_commit)

        assert code == 500, data
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_DECISION_ERROR"
        assert _evidences(client, ws_id, rid, h) == ev_before
        assert _findings_map(client, ws_id, rid, h) == finding_before
        assert db_session.scalar(select(ReviewCandidateDecision)) is None

    def test_decision_requires_completed_verification(self, client, db_session):
        """VerificationRun 未完成 → 409 VERIFICATION_RUN_NOT_COMPLETED。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        verification = db_session.scalar(
            select(ReviewVerificationRun).where(ReviewVerificationRun.id == vrid)
        )
        verification.status = "running"
        db_session.commit()
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 409
        assert data["detail"]["error_code"] == "VERIFICATION_RUN_NOT_COMPLETED"

    def test_invalid_inputs_422(self, client, db_session):
        """非法 decision / rank / note → 422。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "maybe",
        )
        assert code == 422
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], 0, "accept",
        )
        assert code == 422
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "reject",
            note="x" * 501,
        )
        assert code == 422
        # 不存在的 rank → 404
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], 9999, "accept",
        )
        assert code == 404
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_NOT_FOUND"


# ── 12-17. 服务端重新校验 ─────────────────────────────────────────


class TestServerRevalidation:
    def _tamper_output(self, db_session, tool_call_id, rank, field, value):
        tc = db_session.scalar(
            select(ReviewToolCall).where(ReviewToolCall.id == tool_call_id)
        )
        output = json.loads(tc.output_json)
        for r in output["results"]:
            if r.get("rank") == rank:
                r[field] = value
        tc.output_json = json.dumps(output, ensure_ascii=False)
        db_session.commit()

    def test_tampered_output_rejected(self, client, db_session):
        """ToolCall output 被篡改（file_id 指向他处）→ 拒绝，不创建 Evidence。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        self._tamper_output(
            db_session, cand["tool_call_id"], cand["candidate_rank"],
            "file_id", cand["file_id"] + 100000,
        )
        ev_before = _evidences(client, ws_id, rid, h)
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 422, data
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_INVALID"
        assert _evidences(client, ws_id, rid, h) == ev_before
        assert db_session.scalar(select(ReviewCandidateDecision)) is None

    def test_content_hash_mismatch_stale(self, client, db_session):
        """content_hash 不一致 → 409 VERIFICATION_CANDIDATE_STALE。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        self._tamper_output(
            db_session, cand["tool_call_id"], cand["candidate_rank"],
            "content_hash", "0" * 64,
        )
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 409
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_STALE"

    def test_index_sha_change_stale(self, client, db_session, tmp_path, monkeypatch):
        """索引资产不可用（index SHA 与候选产生时不一致）→ stale，不静默用旧索引。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        assert cand["index_sha256"], "hybrid 检索应记录 index_sha256"
        # 把索引根指向一个空的隔离目录：当前索引 SHA 变为空，
        # 与候选产生时记录的 index_sha256 不一致
        import app.services.engineering_retrieval_service as svc_mod

        empty_root = tmp_path / "retrieval-empty" / "workspaces"
        empty_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(svc_mod, "_INDEX_ROOT", empty_root, raising=True)
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 409
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_STALE"

    def test_role_change_stale(self, client, db_session):
        """角色变化（corpus SHA 变化）→ stale。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        r = client.get(f"/api/v2/workspaces/{ws_id}/files", headers=h)
        first = r.json()[0]
        client.patch(
            f"/api/v2/workspaces/{ws_id}/files/{first['file_id']}/profile",
            headers=h,
            json={"confirmed_role": "supplementary_attachment"},
        )
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 409
        assert data["detail"]["error_code"] == "VERIFICATION_CANDIDATE_STALE"

    def test_text_chunk_uses_real_chunk_index(self, client, db_session):
        """text_chunk 采纳后 Evidence.chunk_id 为真实 text_chunk_index（非字符串截取）。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates, locator_type="text_chunk")
        if cand is None:
            # 确定性计划未命中 md 时，用真实检索工具补充一条命中澄清文件的候选
            cand = self._add_text_chunk_candidate(
                client, db_session, ws_id, rid, vrid, h
            )
        assert cand is not None, "应存在 text_chunk 候选"
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 201, data
        evs = _evidences(client, ws_id, rid, h)
        ev = next(e for e in evs if e["id"] == data["evidence_id"])
        assert ev["locator_type"] == "text_chunk"
        # chunk_id 必须是整数且来自当前真实 Corpus 的 text_chunk_index
        from app.models.review_run import ReviewRun
        from app.services.engineering_retrieval_service import build_workspace_corpus

        owner_id = db_session.scalar(
            select(ReviewRun.owner_user_id).where(ReviewRun.id == rid)
        )
        corpus, _ = build_workspace_corpus(db_session, ws_id, owner_id)
        chunk = next(c for c in corpus if c.chunk_id == cand["chunk_id"])
        assert ev["chunk_id"] == chunk.text_chunk_index
        assert isinstance(ev["chunk_id"], int) and ev["chunk_id"] >= 1

    def _add_text_chunk_candidate(self, client, db_session, ws_id, rid, vrid, h):
        from app.agents.engineering_tool_registry import (
            ALLOWED_AGENT_TYPE,
            ENGINEERING_TOOL_HYBRID_RETRIEVAL,
            execute_engineering_tool,
        )

        verification = db_session.scalar(
            select(ReviewVerificationRun).where(ReviewVerificationRun.id == vrid)
        )
        verification.tool_budget = 50
        db_session.commit()
        finding = db_session.scalar(
            select(ReviewFinding).where(ReviewFinding.review_run_id == rid)
        )
        output, call = execute_engineering_tool(
            db_session,
            agent_type=ALLOWED_AGENT_TYPE,
            tool_name=ENGINEERING_TOOL_HYBRID_RETRIEVAL,
            input_data={
                "finding_id": finding.id,
                "query": "澄清 证书编号 可追溯 资质",
                "top_k": 10,
                "retrieval_mode": "hybrid_rrf",
                "reason": "补充 text_chunk 候选",
            },
            verification_run=verification,
            review_run_id=rid,
            review_finding_id=finding.id,
            workspace_id=ws_id,
            owner_user_id=verification.owner_user_id,
            node_name="verification",
            attempt_number=1,
        )
        assert output.get("results")
        payload = _candidates(client, ws_id, rid, vrid, h)
        for cand in payload["candidates"]:
            if cand["tool_call_id"] == call.id and cand["locator_type"] == "text_chunk":
                return cand
        return None

    def test_pdf_excel_locator_preserved(self, client, db_session):
        """PDF/Excel 候选采纳后 locator 保持真实（页码/工作表/单元格）。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        pdf_cand = _pick(candidates, locator_type="pdf_page")
        xls_cand = _pick(candidates, locator_type="spreadsheet_cell")
        assert pdf_cand is not None, "应存在 pdf_page 候选"
        assert xls_cand is not None, "应存在 spreadsheet_cell 候选"

        code, data = _decide(
            client, ws_id, rid, vrid, h,
            pdf_cand["tool_call_id"], pdf_cand["candidate_rank"], "accept",
        )
        assert code == 201
        evs = _evidences(client, ws_id, rid, h)
        ev = next(e for e in evs if e["id"] == data["evidence_id"])
        assert ev["locator_type"] == "pdf_page"
        assert ev["page_number"] == pdf_cand["page_number"]
        assert ev["chunk_id"] is None

        code, data = _decide(
            client, ws_id, rid, vrid, h,
            xls_cand["tool_call_id"], xls_cand["candidate_rank"], "accept",
        )
        assert code == 201
        evs = _evidences(client, ws_id, rid, h)
        ev = next(e for e in evs if e["id"] == data["evidence_id"])
        assert ev["locator_type"] == "spreadsheet_cell"
        assert ev["sheet_name"] == xls_cand["sheet_name"]
        assert ev["cell_range"] == xls_cand["cell_range"]


# ── 18-21. 隔离与级联 ─────────────────────────────────────────────


class TestIsolationAndCascade:
    def test_cross_user_404(self, client, db_session):
        """跨用户访问 candidates / decisions → 404。"""
        ws_id, h, rid = _full_ready(client, db_session, username="alice4c3")
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        _add_user(db_session, "bob4c3")
        r = client.post("/api/v2/auth/logout", headers=h)
        assert r.status_code == 200
        assert _login(client, "bob4c3").status_code == 200
        h2 = _session_csrf(client)
        base = f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs/{vrid}"
        r = client.get(f"{base}/candidates", headers=h2)
        assert r.status_code == 404
        r = client.get(f"{base}/candidate-decisions", headers=h2)
        assert r.status_code == 404
        r = client.post(
            f"{base}/candidate-decisions",
            headers=h2,
            json={
                "tool_call_id": cand["tool_call_id"],
                "candidate_rank": cand["candidate_rank"],
                "decision": "accept",
            },
        )
        assert r.status_code == 404

    def test_cross_workspace_404(self, client, db_session):
        """同用户跨 workspace 访问 → 404。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        ws2 = _eng_ws(client, h, name="第二个工程")
        base = f"/api/v2/workspaces/{ws2}/review-runs/{rid}/verification-runs/{vrid}"
        r = client.get(f"{base}/candidates", headers=h)
        assert r.status_code == 404
        r = client.post(
            f"{base}/candidate-decisions",
            headers=h,
            json={
                "tool_call_id": cand["tool_call_id"],
                "candidate_rank": cand["candidate_rank"],
                "decision": "accept",
            },
        )
        assert r.status_code == 404

    def test_general_workspace_403(self, client, db_session):
        """general workspace → 403。"""
        _add_user(db_session, "gen4c3")
        assert _login(client, "gen4c3").status_code == 200
        h = _session_csrf(client)
        r = client.post(
            "/api/v2/workspaces",
            json={"name": "通用", "workspace_type": "general"},
            headers=h,
        )
        ws_id = r.json()["id"]
        base = f"/api/v2/workspaces/{ws_id}/review-runs/1/verification-runs/1"
        r = client.get(f"{base}/candidates", headers=h)
        assert r.status_code == 403
        r = client.post(
            f"{base}/candidate-decisions",
            headers=h,
            json={"tool_call_id": 1, "candidate_rank": 1, "decision": "accept"},
        )
        assert r.status_code == 403

    def test_workspace_delete_cascades_decisions(self, client, db_session):
        """workspace 永久删除 → CandidateDecision 级联清除。"""
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        code, data = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 201
        assert db_session.scalar(select(ReviewCandidateDecision)) is not None
        r = client.get(f"/api/v2/workspaces/{ws_id}", headers=h)
        ws_name = r.json()["name"]
        r = client.request(
            "DELETE",
            f"/api/v2/workspaces/{ws_id}",
            headers=h,
            json={"confirmation_name": ws_name},
        )
        assert r.status_code == 200
        assert db_session.scalar(
            select(ReviewCandidateDecision).where(
                ReviewCandidateDecision.workspace_id == ws_id
            )
        ) is None


# ── 22-24. 报告不可变与新版本语义 ──────────────────────────────────


class TestReportImmutability:
    def _generate_report(self, c, ws_id, rid, h):
        r = c.post(
            f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/reports", headers=h, json={}
        )
        return r.status_code, r.json()

    def _report_snapshot(self, db_session):
        rows = {}
        for r in db_session.scalars(select(ReviewReport)).all():
            rows[r.id] = (r.version, r.review_state_hash, r.review_snapshot_json,
                          r.quality_gate_json)
        assets = {}
        from app.services.review_report_service import _resolve_storage_path
        for asset in db_session.scalars(select(ReviewReportAsset)).all():
            p = _resolve_storage_path(asset.storage_path)
            if p.exists():
                assets[asset.id] = hashlib.sha256(p.read_bytes()).hexdigest()
        return rows, assets

    def test_v1_report_immutable_after_accept(self, client, db_session):
        """accept 后 v1 的 state hash / 快照 / 资产 SHA 全部不变，且不自动生成 v2。"""
        ws_id, h, rid = _full_ready(client, db_session)
        code, report = self._generate_report(client, ws_id, rid, h)
        assert code == 201, report
        assert report["version"] == 1
        rows_before, assets_before = self._report_snapshot(db_session)

        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 201

        rows_after, assets_after = self._report_snapshot(db_session)
        assert rows_after == rows_before, "历史报告记录被修改"
        assert assets_after == assets_before, "历史报告资产被修改"
        assert len(rows_after) == 1, "不得自动生成 v2"

    def test_manual_generate_creates_v2_with_new_evidence(self, client, db_session):
        """用户主动生成 → 因 Finding Evidence 变化产生 v2，v1 仍可下载且内容不变。"""
        ws_id, h, rid = _full_ready(client, db_session)
        code, report_v1 = self._generate_report(client, ws_id, rid, h)
        assert code == 201
        rows_v1, assets_v1 = self._report_snapshot(db_session)

        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        code, decision = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 201

        code, report_v2 = self._generate_report(client, ws_id, rid, h)
        assert code == 201, report_v2
        assert report_v2["reused"] is False
        assert report_v2["version"] == 2
        assert report_v2["review_state_hash"] != report_v1["review_state_hash"]

        # v2 快照引用新接受的 Evidence
        v2_row = db_session.scalar(
            select(ReviewReport).where(ReviewReport.version == 2)
        )
        assert str(decision["evidence_id"]) in v2_row.review_snapshot_json

        # v1 不可变
        rows_now, _ = self._report_snapshot(db_session)
        assert rows_now[report_v1["id"]] == rows_v1[report_v1["id"]]

        # v1 资产仍可下载且内容不变
        r = client.get(
            f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/reports/{report_v1['id']}/assets",
            headers=h,
        )
        assert r.status_code == 200
        for asset in r.json():
            dl = client.get(
                f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/reports/"
                f"{report_v1['id']}/assets/{asset['id']}/download",
                headers=h,
            )
            assert dl.status_code == 200
            assert hashlib.sha256(dl.content).hexdigest() == assets_v1[asset["id"]]

    def test_reject_keeps_report_state_hash(self, client, db_session):
        """reject 不改变 review_state_hash，再次生成复用 v1（200 reused=true）。"""
        ws_id, h, rid = _full_ready(client, db_session)
        code, report_v1 = self._generate_report(client, ws_id, rid, h)
        assert code == 201

        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "reject",
        )
        assert code == 201

        code, report_again = self._generate_report(client, ws_id, rid, h)
        assert code == 200, report_again
        assert report_again["reused"] is True
        assert report_again["id"] == report_v1["id"]
        assert report_again["review_state_hash"] == report_v1["review_state_hash"]
        rows, _ = self._report_snapshot(db_session)
        assert len(rows) == 1, "reject 不应产生新报告版本"


# ── 25. 迁移 roundtrip ────────────────────────────────────────────


class TestMigration:
    def test_0012_roundtrip(self, tmp_path, monkeypatch):
        """0011 → 0012 upgrade → 0011 downgrade → 0012 re-upgrade。"""
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect

        backend = Path(__file__).resolve().parents[1]
        db_path = tmp_path / "v4c3.db"
        monkeypatch.setenv(
            "ALEMBIC_DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}"
        )
        monkeypatch.setenv("LLM_ENABLED", "false")
        monkeypatch.setenv("LLM_API_KEY", "")
        cfg = Config(str(backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend / "alembic"))

        command.upgrade(cfg, "20260808_0012")
        engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
        inspector = inspect(engine)
        assert "review_candidate_decisions" in inspector.get_table_names()
        columns = {c["name"] for c in inspector.get_columns("review_candidate_decisions")}
        assert {
            "id", "verification_run_id", "review_tool_call_id", "review_finding_id",
            "review_run_id", "workspace_id", "owner_user_id", "candidate_rank",
            "candidate_chunk_id", "candidate_content_hash", "decision",
            "candidate_snapshot_json", "evidence_id", "review_note", "created_at",
        }.issubset(columns)
        uniques = {
            tuple(u["column_names"])
            for u in inspector.get_unique_constraints("review_candidate_decisions")
        }
        assert ("review_tool_call_id", "candidate_rank") in uniques
        engine.dispose()

        command.downgrade(cfg, "20260808_0011")
        engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
        inspector = inspect(engine)
        assert "review_candidate_decisions" not in inspector.get_table_names()
        assert "review_verification_runs" in inspector.get_table_names()
        engine.dispose()

        command.upgrade(cfg, "20260808_0012")
        engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
        inspector = inspect(engine)
        assert "review_candidate_decisions" in inspector.get_table_names()
        engine.dispose()


# ── 26. 默认目录零污染 ────────────────────────────────────────────


class TestZeroPollution:
    def test_default_dirs_untouched(self, client, db_session):
        """完整流程后默认 app.db / uploads / retrieval 零变化。"""
        default_db = BACKEND_DIR / "data" / "app.db"
        default_uploads = BACKEND_DIR / "storage" / "uploads"
        default_retrieval = BACKEND_DIR / "storage" / "retrieval"

        def _snapshot():
            db_hash = (
                hashlib.sha256(default_db.read_bytes()).hexdigest()
                if default_db.exists() else None
            )
            upload_files = (
                sorted(p.relative_to(default_uploads).as_posix()
                       for p in default_uploads.rglob("*") if p.is_file())
                if default_uploads.exists() else []
            )
            retrieval_files = (
                sorted(p.relative_to(default_retrieval).as_posix()
                       for p in default_retrieval.rglob("*") if p.is_file())
                if default_retrieval.exists() else []
            )
            return db_hash, upload_files, retrieval_files

        before = _snapshot()
        ws_id, h, rid = _full_ready(client, db_session)
        vrid, candidates = _verification_with_candidates(
            client, db_session, h=h, ws_id=ws_id, rid=rid
        )
        cand = _pick(candidates)
        code, _ = _decide(
            client, ws_id, rid, vrid, h,
            cand["tool_call_id"], cand["candidate_rank"], "accept",
        )
        assert code == 201
        assert _snapshot() == before, "默认 app.db/uploads/retrieval 被测试污染"
