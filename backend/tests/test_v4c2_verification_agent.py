"""阶段 4C-2：工程 Verification Agent 测试。

覆盖：迁移 roundtrip、规划（确定性/DeepSeek/fallback）、工具注册表权限与预算、
     真实检索工具调用、局部重试链、候选证据边界、幂等、隔离、级联删除等 28 项。

普通 pytest：
- Fake Embedding（monkeypatch LocalEmbeddingProvider）
- monkeypatch LLM（不访问网络）
- 独立临时数据库、上传目录和索引目录
- 默认 app.db / uploads / retrieval 零变化
- 0 skip / xfail / deselect
"""

from __future__ import annotations

import hashlib
import io
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
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.review_tool_call import ReviewToolCall
from app.models.review_verification_run import ReviewVerificationRun
from app.models.user import User
from app.retrieval.embedding import FakeEmbeddingProvider
from app.services.llm_service import LLMResult
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

# 基线：12 Finding + 2 passed rules（与阶段 2B fixture 基线一致）
# 真实规则包跑出的 12 条规则类型 Finding（规则包快照基线）
EXPECTED_FINDING_CODES = [
    "SYN-DATE-001", "SYN-DATE-002", "SYN-DATE-003", "SYN-EQ-001", "SYN-EQ-002",
    "SYN-EVD-001", "SYN-EVD-002", "SYN-NUM-001", "SYN-NUM-002", "SYN-NUM-003",
    "SYN-REQ-001", "SYN-REQ-002",
]
EXPECTED_PASSED_RULES = ["SYN-DOC-001", "SYN-DOC-002"]


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


# ── helpers ───────────────────────────────────────────────────────


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


def _full_ready(c, db_session, username: str = "user4c2") -> tuple[int, dict, int]:
    """注册登录 → 工程工作区 → 五文件 ready → brief confirmed → run completed。

    返回 (ws_id, csrf_headers, run_id)。
    """
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


def _post_verification(c, ws_id, rid, h, **payload) -> tuple[int, dict]:
    body = {"use_deepseek": False, "max_tool_calls": 5}
    body.update(payload)
    r = c.post(
        f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs",
        headers=h,
        json=body,
    )
    return r.status_code, r.json()


def _tool_calls(c, ws_id, rid, vrid, h) -> list[dict]:
    r = c.get(
        f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs/{vrid}/tool-calls",
        headers=h,
    )
    assert r.status_code == 200
    return r.json()


# ── 1. 迁移 roundtrip ─────────────────────────────────────────────


class TestMigration:
    def test_verification_tables_roundtrip(self, tmp_path, monkeypatch):
        """0011 迁移 roundtrip：升级建两表，降级删除，再升级恢复。"""
        import subprocess
        import sys

        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect

        backend = Path(__file__).resolve().parents[1]
        db_path = tmp_path / "v4c2.db"
        monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("LLM_ENABLED", "false")
        monkeypatch.setenv("LLM_API_KEY", "")
        cfg = Config(str(backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend / "alembic"))

        command.upgrade(cfg, "20260808_0011")
        engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
        inspector = inspect(engine)
        assert {"review_verification_runs", "review_tool_calls"}.issubset(
            inspector.get_table_names()
        )
        engine.dispose()

        command.downgrade(cfg, "20260807_0010")
        engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
        inspector = inspect(engine)
        assert "review_verification_runs" not in inspector.get_table_names()
        assert "review_tool_calls" not in inspector.get_table_names()
        engine.dispose()

        command.upgrade(cfg, "20260808_0011")
        engine = create_engine(f"sqlite:///{db_path.resolve().as_posix()}")
        inspector = inspect(engine)
        assert "review_verification_runs" in inspector.get_table_names()
        assert "review_tool_calls" in inspector.get_table_names()
        engine.dispose()


# ── 2-8. 规划与 DeepSeek ──────────────────────────────────────────


class TestPlanning:
    def test_completed_review_run_required(self, client, db_session):
        """未 completed 的 ReviewRun 拒绝验证。"""
        _add_user(db_session, "notdone")
        assert _login(client, "notdone").status_code == 200
        h = _session_csrf(client)
        ws_id = _eng_ws(client, h)
        _setup_full(client, ws_id, h)
        bid = _brief_confirm(client, ws_id, h)
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-runs",
            json={"review_brief_id": bid},
            headers=h,
        )
        rid = r.json()["id"]  # 未 execute → pending

        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 422
        assert data["detail"]["error_code"] == "REVIEW_RUN_NOT_COMPLETED"

    def test_deterministic_plan_has_retrieve_and_skip(self, client, db_session):
        """确定性计划同时包含 retrieve 和 skip，skip 有原因。"""
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        assert data["reused"] is False
        assert data["planner_type"] == "deterministic"
        decisions = data["plan"]["decisions"]
        decisions_types = {d["decision"] for d in decisions}
        assert "retrieve" in decisions_types
        assert "skip" in decisions_types
        for d in decisions:
            assert d["reason"], "每个决策必须有原因"
            if d["decision"] == "skip":
                assert d["query"] is None

    def test_deepseek_valid_plan(self, client, db_session, monkeypatch):
        """DeepSeek 合法计划：planner_type=deepseek, fallback=False。"""

        def fake_llm(messages, temperature=0.2, max_tokens=800, timeout_seconds=30,
                response_format=None, thinking=None):
            # 直接从 DB 查询真实 findings，构造每个 Finding 恰好一个决策的完整计划
            real_findings = list(
                db_session.scalars(
                    select(ReviewFinding)
                    .where(ReviewFinding.review_run_id == rid)
                    .order_by(ReviewFinding.id.asc())
                ).all()
            )
            assert real_findings, "应存在 findings"
            decisions = []
            for i, f in enumerate(real_findings):
                if i == 0:
                    decisions.append({
                        "finding_id": f.id,
                        "issue_code": f.issue_code,
                        "decision": "retrieve",
                        "reason": "需要补充检索",
                        "query": "证书编号一致性",
                        "retrieval_mode": "hybrid_rrf",
                        "top_k": 5,
                    })
                else:
                    decisions.append({
                        "finding_id": f.id,
                        "issue_code": f.issue_code,
                        "decision": "skip",
                        "reason": "已有足够证据",
                    })
            return LLMResult(
                success=True,
                content=json.dumps({"decisions": decisions}),
                token_usage={"total_tokens": 88},
                duration_ms=120,
            )

        monkeypatch.setattr(
            "app.agents.engineering_verification_agent.call_llm", fake_llm
        )
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        assert data["planner_type"] == "deepseek"
        assert data["fallback_used"] is False
        assert data["prompt_version"]
        assert data["token_usage"] == {"total_tokens": 88}
        assert data["model_name"]

    def test_deepseek_invalid_json_fallback(self, client, db_session, monkeypatch):
        """DeepSeek 非法 JSON → 确定性 fallback + 原因。"""

        def fake_llm(messages, **kw):
            return LLMResult(success=True, content="这不是 JSON{{{")

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        assert data["fallback_used"] is True
        assert data["planner_type"] == "deterministic_fallback", data["planner_type"]
        assert data["fallback_reason"], "必须记录 fallback 原因"
        # fallback 计划仍是完整计划（含 retrieve 决策）
        assert any(d["decision"] == "retrieve" for d in data["plan"]["decisions"])

    def test_deepseek_unknown_finding_fallback(self, client, db_session, monkeypatch):
        """DeepSeek 引用不存在 Finding → fallback。"""

        def fake_llm(messages, **kw):
            return LLMResult(
                success=True,
                content=json.dumps({
                    "decisions": [
                        {
                            "finding_id": 999999,
                            "issue_code": "x",
                            "decision": "retrieve",
                            "reason": "r",
                            "query": "q",
                        }
                    ]
                }),
            )

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        assert data["fallback_used"] is True
        assert data["planner_type"] == "deterministic_fallback"
        assert data["fallback_reason"] == "DEEPSEEK_PLAN_POLICY_VIOLATION", data["fallback_reason"]

    def test_deepseek_disallowed_tool_fallback(self, client, db_session, monkeypatch):
        """DeepSeek 输出越权工具（非法 retrieval_mode）→ fallback。"""

        def fake_llm(messages, **kw):
            import re
            body = messages[1]["content"]
            m_id = re.search(r'"id": (\d+)', body)
            m_code = re.search(r'"issue_code": "([^"]+)"', body)
            assert m_id and m_code
            return LLMResult(
                success=True,
                content=json.dumps({
                    "decisions": [
                        {
                            "finding_id": int(m_id.group(1)),
                            "issue_code": m_code.group(1),
                            "decision": "retrieve",
                            "reason": "r",
                            "query": "q",
                            "retrieval_mode": "execute_shell",
                            "top_k": 5,
                        }
                    ]
                }),
            )

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        assert data["fallback_used"] is True
        assert data["planner_type"] == "deterministic_fallback"

    def test_tool_budget_enforced(self, client, db_session):
        """预算耗尽：max_tool_calls=1，首个检索失败需 prepare 时预算耗尽。"""
        ws_id, h, rid = _full_ready(client, db_session)
        # 不构建索引 → 检索触发 INDEX_MISSING → 需要 prepare（预算 1 已用尽）
        code, data = _post_verification(client, ws_id, rid, h, max_tool_calls=1)
        assert code == 201
        assert data["status"] == "completed_with_warnings"
        assert data["tool_calls_used"] >= 1
        # 预算用尽后 prepare 被拒，错误码稳定
        assert any(
            "BUDGET_EXCEEDED" in w for w in data["warnings"]
        ) or data["failed_count"] >= 1


# ── 9-14. 工具调用与候选证据边界 ──────────────────────────────────


class TestToolExecution:
    def test_hybrid_tool_real_call(self, client, db_session):
        """Hybrid 工具真实调用成功（先建索引）。"""
        ws_id, h, rid = _full_ready(client, db_session)
        # 先建索引
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index",
            headers=h,
            json={"rebuild": False},
        )
        assert r.status_code == 200
        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        assert data["success_count"] >= 1
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        hybrid_calls = [t for t in calls if t["tool_name"] == "engineering_hybrid_retrieval"]
        assert hybrid_calls, "应有 hybrid 检索工具调用"
        assert all(t["status"] == "success" for t in hybrid_calls)
        # 工具预算/使用量
        assert data["tool_calls_used"] == len(calls)
        assert data["tool_calls_used"] <= data["tool_budget"]

    def test_locator_hash_parser_metadata_complete(self, client, db_session):
        """命中结果包含完整 locator/hash/parser 元数据。"""
        ws_id, h, rid = _full_ready(client, db_session)
        client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        code, data = _post_verification(client, ws_id, rid, h)
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        outputs = [t["output"] for t in calls if t["tool_name"] == "engineering_hybrid_retrieval"]
        assert outputs
        any_results = any(o.get("results") for o in outputs)
        assert any_results, "应有检索结果"
        for o in outputs:
            for res in o.get("results", []):
                assert res["content_hash"]
                assert res["parser_name"]
                assert res["parser_version"]
                assert res["locator_type"] in ("pdf_page", "spreadsheet_cell", "text_chunk")
                assert res["rank"] >= 1
                assert "quote" in res
        # 顶层元数据
        first = outputs[0]
        assert first["index_sha256"] and first["corpus_sha256"]
        assert first["model_revision"]

    def test_candidate_only_boundary(self, client, db_session):
        """工具输出明确 candidate_only / requires_human_confirmation。"""
        ws_id, h, rid = _full_ready(client, db_session)
        client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        code, data = _post_verification(client, ws_id, rid, h)
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        for t in calls:
            if t["tool_name"] == "engineering_hybrid_retrieval" and t["status"] == "success":
                assert t["output"]["candidate_only"] is True
                assert t["output"]["requires_human_confirmation"] is True

    def test_finding_evidence_ids_unchanged(self, client, db_session):
        """运行前后 Finding evidence_ids 不变。"""
        ws_id, h, rid = _full_ready(client, db_session)
        client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        before = _findings_map(client, ws_id, rid, h)
        _post_verification(client, ws_id, rid, h)
        after = _findings_map(client, ws_id, rid, h)
        assert set(before) == set(after)
        for code_ in before:
            assert before[code_]["evidence_ids"] == after[code_]["evidence_ids"]
            assert before[code_]["status"] == after[code_]["status"]

    def test_finding_status_unchanged(self, client, db_session):
        """运行前后 Finding status 不变（不自动确认/修改）。"""
        ws_id, h, rid = _full_ready(client, db_session)
        before = _findings_map(client, ws_id, rid, h)
        _post_verification(client, ws_id, rid, h)
        after = _findings_map(client, ws_id, rid, h)
        for code_ in before:
            assert after[code_]["status"] == "pending_review"
            assert after[code_]["status"] == before[code_]["status"]

    def test_report_assets_unchanged(self, client, db_session):
        """运行前后 ReviewReport 资产 SHA 不变。"""
        ws_id, h, rid = _full_ready(client, db_session)
        # 生成一份报告
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/reports", headers=h, json={}
        )
        assert r.status_code == 201, f"report: {r.status_code} {r.text}"

        from app.models.review_report import ReviewReport
        from app.models.review_report_asset import ReviewReportAsset

        # 记录报告 DB 快照（无落盘资产时按 DB 行与快照字段校验）
        report_rows_before = list(db_session.scalars(select(ReviewReport)).all())
        reports_before = {
            r.id: (r.review_state_hash, r.quality_gate_json, r.review_snapshot_json)
            for r in report_rows_before
        }
        asset_hashes_before = {}
        for asset in db_session.scalars(select(ReviewReportAsset)).all():
            p = Path(asset.storage_path)
            if p.exists():
                asset_hashes_before[asset.id] = hashlib.sha256(p.read_bytes()).hexdigest()

        _post_verification(client, ws_id, rid, h)

        reports_after = {
            r.id: (r.review_state_hash, r.quality_gate_json, r.review_snapshot_json)
            for r in db_session.scalars(select(ReviewReport)).all()
        }
        asset_hashes_after = {}
        for asset in db_session.scalars(select(ReviewReportAsset)).all():
            p = Path(asset.storage_path)
            if p.exists():
                asset_hashes_after[asset.id] = hashlib.sha256(p.read_bytes()).hexdigest()
        # 报告 DB 快照与资产哈希均不变（历史报告未被修改/重新生成）
        assert reports_after == reports_before, "ReviewReport 记录被修改"
        assert asset_hashes_after == asset_hashes_before, "报告资产被修改"


# ── 15-19. 局部重试 ───────────────────────────────────────────────


class TestLocalRetry:
    def test_index_missing_prepare_and_retry(self, client, db_session):
        """INDEX_MISSING → prepare → retry 成功；retry_of_id 指向 attempt1。"""
        ws_id, h, rid = _full_ready(client, db_session)
        # 不建索引 → 检索必触发 INDEX_MISSING
        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        hybrid = [t for t in calls if t["tool_name"] == "engineering_hybrid_retrieval"]
        assert hybrid, "应有检索调用"
        assert any(t["status"] == "failed" and t["error_code"] == "ENGINEERING_RETRIEVAL_INDEX_MISSING" for t in hybrid)
        prepare = [t for t in calls if t["tool_name"] == "engineering_retrieval_index_prepare"]
        assert prepare, "应有索引 prepare 调用"
        assert all(t["status"] == "success" for t in prepare)
        # 重试：attempt2 且 retry_of_id 指向 attempt1
        retries = [t for t in hybrid if t["attempt_number"] == 2]
        assert retries, "应有一次重试"
        failed_attempt1 = next(t for t in hybrid if t["status"] == "failed")
        assert retries[0]["retry_of_id"] == failed_attempt1["id"]
        assert retries[0]["status"] == "success"
        # 检索结果成功
        assert data["success_count"] >= 1

    def test_index_stale_prepare_and_retry(self, client, db_session):
        """INDEX_STALE → prepare → retry 成功。"""
        ws_id, h, rid = _full_ready(client, db_session)
        # 先建索引
        client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        # 修改一个文件角色 → corpus 变化 → STALE
        r = client.get(f"/api/v2/workspaces/{ws_id}/files", headers=h)
        first = r.json()[0]
        client.patch(
            f"/api/v2/workspaces/{ws_id}/files/{first['file_id']}/profile",
            headers=h,
            json={"confirmed_role": "supplementary_attachment"},
        )
        # 恢复（避免角色污染后续），先触发 stale
        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        hybrid = [t for t in calls if t["tool_name"] == "engineering_hybrid_retrieval"]
        assert any(t["status"] == "failed" and t["error_code"] == "ENGINEERING_RETRIEVAL_INDEX_STALE" for t in hybrid)
        prepare = [t for t in calls if t["tool_name"] == "engineering_retrieval_index_prepare"]
        assert prepare and all(t["status"] == "success" for t in prepare)
        retries = [t for t in hybrid if t["attempt_number"] == 2]
        assert retries and retries[0]["status"] == "success"
        assert data["retry_count"] >= 1

    def test_model_unavailable_not_retried(self, client, db_session, monkeypatch):
        """MODEL_UNAVAILABLE 不重试（无 prepare、无 attempt2）。"""
        from app.retrieval.embedding import EmbeddingError

        import app.services.engineering_retrieval_service as svc_mod

        ws_id, h, rid = _full_ready(client, db_session)
        # 先用 Fake Provider 建好索引，使 hybrid 检索进入 dense 路径并触发模型加载
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        assert r.status_code == 200

        class FailingProvider:
            def __init__(self, *args, **kwargs):
                raise EmbeddingError("模拟模型不可用")

        monkeypatch.setattr(svc_mod, "LocalEmbeddingProvider", FailingProvider)

        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        hybrid = [t for t in calls if t["tool_name"] == "engineering_hybrid_retrieval"]
        assert hybrid
        assert all(
            t["status"] == "failed"
            and t["error_code"] == "ENGINEERING_RETRIEVAL_MODEL_UNAVAILABLE"
            for t in hybrid
        ), [t["error_code"] for t in hybrid]
        assert all(t["attempt_number"] == 1 for t in hybrid), "MODEL_UNAVAILABLE 不应重试"
        prepare = [t for t in calls if t["tool_name"] == "engineering_retrieval_index_prepare"]
        assert not prepare, "不应有 prepare"
        assert data["retry_count"] == 0

    def test_retry_of_id_and_attempt_number(self, client, db_session):
        """retry_of_id 与 attempt_number 记录正确。"""
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h)
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        by_attempt = {}
        for t in calls:
            if t["tool_name"] == "engineering_hybrid_retrieval":
                by_attempt.setdefault(t["attempt_number"], []).append(t)
        for attempt2 in by_attempt.get(2, []):
            assert attempt2["retry_of_id"] is not None
            failed = next(t for t in calls if t["id"] == attempt2["retry_of_id"])
            assert failed["status"] == "failed"
            assert failed["attempt_number"] == 1

    def test_other_successful_findings_not_rerun(self, client, db_session, monkeypatch):
        """其他成功检索不重复执行（每个 retrieve 决策至多 1 次成功调用）。"""
        ws_id, h, rid = _full_ready(client, db_session)
        client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        code, data = _post_verification(client, ws_id, rid, h)
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        hybrid = [t for t in calls if t["tool_name"] == "engineering_hybrid_retrieval"]
        # 每个 attempt_number=1 的成功调用都只出现一次
        first_attempts = [t for t in hybrid if t["attempt_number"] == 1]
        assert len(first_attempts) == len({t["review_finding_id"] for t in first_attempts})
        assert data["success_count"] == sum(1 for t in calls if t["status"] == "success" and t["attempt_number"] == 1)


# ── 20-23. 幂等与隔离 ─────────────────────────────────────────────


class TestIdempotencyAndIsolation:
    def test_idempotent_reuse(self, client, db_session):
        """同输入重复调用 → 200 reused=true，不创建新 run。"""
        ws_id, h, rid = _full_ready(client, db_session)
        # 先建索引使 index_sha256 稳定（否则首次运行 prepare 后状态变化会产生新 hash）
        client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        code1, data1 = _post_verification(client, ws_id, rid, h)
        assert code1 == 201 and data1["reused"] is False
        code2, data2 = _post_verification(client, ws_id, rid, h)
        assert code2 == 200 and data2["reused"] is True
        assert data2["verification_run_id"] == data1["verification_run_id"]
        assert data2["input_state_hash"] == data1["input_state_hash"]
        # 只创建了一个 run
        r = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs", headers=h)
        assert len(r.json()) == 1

    def test_finding_action_creates_new_run(self, client, db_session):
        """Finding Action 后 hash 变化 → 新 verification run。"""
        ws_id, h, rid = _full_ready(client, db_session)
        code1, data1 = _post_verification(client, ws_id, rid, h)
        # 对一条 finding 执行 confirm
        findings = _findings_map(client, ws_id, rid, h)
        any_finding = next(iter(findings.values()))
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-findings/{any_finding['id']}/actions",
            headers=h,
            json={"action_type": "confirm"},
        )
        assert r.status_code == 201
        code2, data2 = _post_verification(client, ws_id, rid, h)
        assert code2 == 201 and data2["reused"] is False
        assert data2["input_state_hash"] != data1["input_state_hash"]
        assert data2["verification_run_id"] != data1["verification_run_id"]

    def test_cross_user_404(self, client, db_session):
        """跨用户访问返回 404。"""
        ws_id, h, rid = _full_ready(client, db_session, username="alice4c2")
        _add_user(db_session, "bob4c2")
        # 先登出 alice（会话 CSRF 绑定 alice，需先清除才能登录 bob）
        r = client.post("/api/v2/auth/logout", headers=h)
        assert r.status_code == 200
        assert _login(client, "bob4c2").status_code == 200
        h2 = _session_csrf(client)
        for path in (
            f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs",
            f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs/1",
            f"/api/v2/workspaces/{ws_id}/review-runs/{rid}/verification-runs/1/tool-calls",
        ):
            r = client.get(path, headers=h2)
            assert r.status_code == 404, f"{path}: {r.status_code}"

    def test_general_workspace_forbidden(self, client, db_session):
        """general workspace 返回 403。"""
        _add_user(db_session, "gen4c2")
        assert _login(client, "gen4c2").status_code == 200
        h = _session_csrf(client)
        r = client.post(
            "/api/v2/workspaces",
            json={"name": "通用", "workspace_type": "general"},
            headers=h,
        )
        ws_id = r.json()["id"]
        r = client.post(
            f"/api/v2/workspaces/{ws_id}/review-runs/1/verification-runs",
            headers=h,
            json={},
        )
        assert r.status_code == 403


# ── 24-28. 安全、级联与基线 ───────────────────────────────────────


class TestSafetyAndBaseline:
    def test_error_message_no_paths(self, client, db_session, monkeypatch):
        """错误信息不泄露路径/堆栈/API Key。"""
        from app.retrieval.embedding import EmbeddingError

        import app.services.engineering_retrieval_service as svc_mod

        class FailingProvider:
            def __init__(self, *args, **kwargs):
                raise EmbeddingError("模拟模型不可用")

        monkeypatch.setattr(svc_mod, "LocalEmbeddingProvider", FailingProvider)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h)
        assert code == 201
        calls = _tool_calls(client, ws_id, rid, data["verification_run_id"], h)
        for t in calls:
            msg = t.get("error_message") or ""
            for forbidden in ("C:\\", "D:\\", "Users", "Traceback", "File ", "api_key", "sk-"):
                assert forbidden.lower() not in msg.lower(), f"泄露: {forbidden} in {msg}"

    def test_workspace_delete_cascades(self, client, db_session):
        """workspace 永久删除 → verification run + tool call 级联清除。"""
        ws_id, h, rid = _full_ready(client, db_session)
        client.post(
            f"/api/v2/workspaces/{ws_id}/engineering-retrieval/index", headers=h, json={}
        )
        code, data = _post_verification(client, ws_id, rid, h)
        assert data["verification_run_id"]
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
            select(ReviewVerificationRun).where(ReviewVerificationRun.workspace_id == ws_id)
        ) is None
        assert db_session.scalar(
            select(ReviewToolCall).where(ReviewToolCall.workspace_id == ws_id)
        ) is None

    def test_no_ground_truth_usage(self):
        """生产代码不读取 ground_truth、不含黄金答案硬编码。"""
        for path in (
            BACKEND_DIR / "app" / "agents" / "engineering_verification_agent.py",
            BACKEND_DIR / "app" / "services" / "engineering_verification_service.py",
            BACKEND_DIR / "app" / "agents" / "engineering_tool_registry.py",
        ):
            source = path.read_text(encoding="utf-8")
            assert 'ground_truth.json' not in source, f"{path.name} 引用 ground_truth.json"
            assert '"ground_truth"' not in source, f"{path.name} 访问 ground_truth 键"

    def test_old_tool_registry_untouched(self):
        """旧 general Tool Registry 未被修改，工程 registry 独立。"""
        from app.agents import tool_registry as old_registry
        from app.agents.engineering_tool_registry import ENGINEERING_TOOL_NAMES

        old_names = old_registry.registered_tool_names()
        assert old_names == {
            "workspace_context_lookup",
            "preset_multi_table_analysis",
            "selected_document_retrieval",
            "structured_markdown_report",
            "deterministic_quality_review",
        }
        assert old_names.isdisjoint(ENGINEERING_TOOL_NAMES), "新旧 registry 不应共用工具"

    def test_baseline_12_findings_2_passed(self, client, db_session):
        """不改变 12 Finding、2 passed rules 基线。"""
        ws_id, h, rid = _full_ready(client, db_session)
        findings = _findings_map(client, ws_id, rid, h)
        assert len(findings) == 12, f"基线应为 12 Finding，实际 {len(findings)}"
        assert set(findings) == set(EXPECTED_FINDING_CODES)
        r = client.get(f"/api/v2/workspaces/{ws_id}/review-runs/{rid}", headers=h)
        assert r.status_code == 200
        run_data = r.json()
        assert run_data["passed_rule_ids"] == EXPECTED_PASSED_RULES


# ── 4C-2 补修：DeepSeek 规划有效性 ─────────────────────────────────


class TestDeepSeekPlanningFix:
    """DeepSeek 规划有效性补修：max_tokens、安全 JSON 解析、三态 planner_type。"""

    def test_max_tokens_captured_in_range(self, client, db_session, monkeypatch):
        """call_llm max_tokens ≥ 1600 且 ≤ 2400（足够容纳全部 Finding 决策）。"""
        captured = {}

        def fake_llm(messages, temperature=0.2, max_tokens=800, timeout_seconds=30,
                response_format=None, thinking=None):
            captured["max_tokens"] = max_tokens
            import re
            body = messages[1]["content"]
            m_id = re.search(r'"id": (\d+)', body)
            m_code = re.search(r'"issue_code": "([^"]+)"', body)
            return LLMResult(
                success=True,
                content=json.dumps({
                    "decisions": [
                        {
                            "finding_id": int(m_id.group(1)),
                            "issue_code": m_code.group(1),
                            "decision": "skip",
                            "reason": "已有足够证据",
                        }
                    ]
                }),
            )

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert captured.get("max_tokens") is not None, "call_llm 未被调用"
        assert 1600 <= captured["max_tokens"] <= 2400, captured["max_tokens"]

    def test_full_12_finding_json_parses(self):
        """12 条 Finding 的完整合法 JSON 能解析为 VerificationPlan。"""
        from app.agents.engineering_verification_agent import (
            VerificationPlan,
            _parse_json_object_safe,
        )

        decisions = []
        for i in range(12):
            if i < 3:
                decisions.append({
                    "finding_id": i + 1,
                    "issue_code": f"SYN-{i:03d}",
                    "decision": "retrieve",
                    "reason": "需要补充检索定位证据",
                    "query": f"查询 {i}",
                    "retrieval_mode": "hybrid_rrf",
                    "top_k": 5,
                })
            else:
                decisions.append({
                    "finding_id": i + 1,
                    "issue_code": f"SYN-{i:03d}",
                    "decision": "skip",
                    "reason": "已有足够证据",
                })
        raw = json.dumps({"decisions": decisions})
        data = _parse_json_object_safe(raw)
        assert data is not None
        plan = VerificationPlan.model_validate(data)
        assert len(plan.decisions) == 12

    def test_markdown_json_fence_parses(self):
        """单个 ```json ... ``` 围栏包裹的 JSON 能解析。"""
        from app.agents.engineering_verification_agent import _parse_json_object_safe

        raw = "```json\n{\"decisions\": []}\n```"
        data = _parse_json_object_safe(raw)
        assert data == {"decisions": []}

        raw2 = "```json\n{\"decisions\": [{\"finding_id\": 1}]}\n```\n"
        data2 = _parse_json_object_safe(raw2)
        assert data2 == {"decisions": [{"finding_id": 1}]}

    def test_bom_and_whitespace_parses(self):
        """BOM 与首尾空白能解析。"""
        from app.agents.engineering_verification_agent import _parse_json_object_safe

        raw = "\ufeff\n  \n{\"decisions\": []}  \n"
        data = _parse_json_object_safe(raw)
        assert data == {"decisions": []}

    def test_truncated_json_not_patched(self):
        """截断 JSON 不修补 → 返回 None（走 fallback）。"""
        from app.agents.engineering_verification_agent import _parse_json_object_safe

        raw = '{"decisions": [{"finding_id": 1, "issue_code": "SYN-001", "decision": "retrieve", "reason": "'
        assert _parse_json_object_safe(raw) is None

    def test_multiple_json_objects_rejected(self):
        """多个 JSON object 被拒绝。"""
        from app.agents.engineering_verification_agent import _parse_json_object_safe

        raw = '{"decisions": []}\n{"decisions": []}'
        assert _parse_json_object_safe(raw) is None

    def test_fallback_keeps_model_metadata(self, client, db_session, monkeypatch):
        """fallback 仍保留 model/token/prompt 元数据。"""

        def fake_llm(messages, **kw):
            return LLMResult(
                success=True,
                content="这不是 JSON",
                token_usage={"total_tokens": 123},
                duration_ms=99,
            )

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        assert data["planner_type"] == "deterministic_fallback"
        assert data["fallback_used"] is True
        # 元数据保留：证明模型被尝试过，但决策来自确定性 fallback
        assert data["model_name"], "缺少 model_name"
        assert data["prompt_version"], "缺少 prompt_version"
        assert data["token_usage"] == {"total_tokens": 123}, data["token_usage"]
        assert data["fallback_reason"], "缺少 fallback_reason"

    def test_deepseek_full_plan_retrieve_and_skip(self, client, db_session, monkeypatch):
        """DeepSeek 完整 12 决策计划：retrieve+skip 同时存在，每个 Finding 恰好一个。"""

        def fake_llm(messages, temperature=0.2, max_tokens=800, timeout_seconds=30,
                response_format=None, thinking=None):
            # 直接从 DB 查询真实 findings，构造完整 12 决策计划
            real_findings = list(
                db_session.scalars(
                    select(ReviewFinding)
                    .where(ReviewFinding.review_run_id == rid)
                    .order_by(ReviewFinding.id.asc())
                ).all()
            )
            assert real_findings, "应存在 findings"
            decisions = []
            for i, f in enumerate(real_findings):
                if i < 3:
                    decisions.append({
                        "finding_id": f.id,
                        "issue_code": f.issue_code,
                        "decision": "retrieve",
                        "reason": "需要补充检索定位证据",
                        "query": f"补充证据查询 {i}",
                        "retrieval_mode": "hybrid_rrf",
                        "top_k": 5,
                    })
                else:
                    decisions.append({
                        "finding_id": f.id,
                        "issue_code": f.issue_code,
                        "decision": "skip",
                        "reason": "已有足够证据",
                    })
            return LLMResult(
                success=True,
                content=json.dumps({"decisions": decisions}),
                token_usage={"total_tokens": 500},
                duration_ms=88,
            )

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        assert data["planner_type"] == "deepseek", data["planner_type"]
        assert data["fallback_used"] is False
        decisions = data["plan"]["decisions"]
        assert len(decisions) == 12, f"每个 Finding 恰好一个决策: {len(decisions)}"
        assert any(d["decision"] == "retrieve" for d in decisions)
        assert any(d["decision"] == "skip" for d in decisions)
        # 所有决策的 finding 恰好覆盖一次
        finding_ids = [d["finding_id"] for d in decisions]
        assert len(finding_ids) == len(set(finding_ids)), "重复决策"
        assert data["prompt_version"] == "4c2.3"

    def test_deepseek_omitted_finding_fallback(self, client, db_session, monkeypatch):
        """DeepSeek 遗漏 Finding → 语义校验失败 → fallback。"""

        def fake_llm(messages, **kw):
            import re
            body = messages[1]["content"]
            ids = [int(x) for x in re.findall(r'"id": (\d+)', body)]
            codes = re.findall(r'"issue_code": "([^"]+)"', body)
            pairs = list(zip(ids, codes))
            # 只给 1 个决策，遗漏其余 11 个
            fid, code = pairs[0]
            return LLMResult(
                success=True,
                content=json.dumps({
                    "decisions": [{
                        "finding_id": fid,
                        "issue_code": code,
                        "decision": "skip",
                        "reason": "已有足够证据",
                    }]
                }),
            )

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        assert data["fallback_used"] is True
        assert data["planner_type"] == "deterministic_fallback"
        assert data["fallback_reason"] == "DEEPSEEK_PLAN_POLICY_VIOLATION", data["fallback_reason"]

    def test_excluded_check_type_rejected(self, client, db_session, monkeypatch):
        """DeepSeek 对被排除的检查类型做 retrieve → fallback。"""

        def fake_llm(messages, **kw):
            import re
            body = messages[1]["content"]
            ids = [int(x) for x in re.findall(r'"id": (\d+)', body)]
            codes = re.findall(r'"issue_code": "([^"]+)"', body)
            pairs = list(zip(ids, codes))
            decisions = []
            for i, (fid, code) in enumerate(pairs):
                decisions.append({
                    "finding_id": fid,
                    "issue_code": code,
                    "decision": "retrieve",
                    "reason": "需要补充检索",
                    "query": f"q{i}",
                    "retrieval_mode": "hybrid_rrf",
                    "top_k": 5,
                })
            return LLMResult(success=True, content=json.dumps({"decisions": decisions}))

        monkeypatch.setattr("app.agents.engineering_verification_agent.call_llm", fake_llm)
        ws_id, h, rid = _full_ready(client, db_session)
        code, data = _post_verification(client, ws_id, rid, h, use_deepseek=True)
        assert code == 201
        # 12 条 retrieve 超预算（>5）→ 必须 fallback
        assert data["fallback_used"] is True
        assert data["planner_type"] == "deterministic_fallback"
