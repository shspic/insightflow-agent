"""V3 阶段 2A 补修测试：ReviewBrief、Brief⇔Run 绑定、Evidence 真实校验、角色/关系服务集成。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.file import File
from app.models.file_profile import FileProfile
from app.models.file_relation import FileRelation
from app.models.review_brief import ReviewBrief
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.schemas.review import (
    EvidenceCreate,
    InterpretedIntent,
    ReviewBriefCreate,
    ReviewRulePack,
    StructuredFieldValue,
    StructuredReviewInput,
)
from app.services.review_rule_service import (
    RuleLoadError,
    compute_rule_pack_hash,
    compute_rule_snapshot,
    load_rule_pack,
)
from app.services.review_engine_service import (
    execute_all_rules,
    execute_rule,
)
from app.services.review_action_service import (
    ReviewServiceError,
    complete_review_run,
    create_evidence,
    create_review_finding,
    create_review_run,
    execute_review_action,
    fail_review_run,
    list_actions_for_finding,
    start_review_run,
)
from app.services.review_brief_service import (
    BriefServiceError,
    confirm_review_brief,
    create_review_brief,
)
from app.services.file_understanding_service import (
    FileUnderstandingError,
    update_profile_confirmation,
)
from app.services.file_relation_service import (
    FileRelationError,
    mutate_file_relation,
)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://")

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_connection, connection_record):  # noqa: ARG001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def seed_users(db):
    u1 = User(username="alice", password_hash="hash", role="user", status="active", must_change_password=False)
    u2 = User(username="bob", password_hash="hash", role="user", status="active", must_change_password=False)
    db.add_all([u1, u2])
    db.commit()
    return {"alice": u1, "bob": u2}


@pytest.fixture
def seed_engineering_workspace(db, seed_users):
    ws = Workspace(
        owner_user_id=seed_users["alice"].id, name="测试工程项目",
        workspace_type="engineering", review_template_key="engineering_bid_review_v1", status="active",
    )
    db.add(ws)
    db.commit()
    return ws


@pytest.fixture
def seed_general_workspace(db, seed_users):
    ws = Workspace(
        owner_user_id=seed_users["alice"].id, name="通用工作区",
        workspace_type="general", review_template_key=None, status="active",
    )
    db.add(ws)
    db.commit()
    return ws


@pytest.fixture
def rule_pack():
    return load_rule_pack("engineering_bid_review_v1")


@pytest.fixture
def seed_file(db, seed_users, seed_engineering_workspace):
    """创建真实 File 和 WorkspaceFile。"""
    f = File(owner_user_id=seed_users["alice"].id, filename="test.pdf", file_type="pdf",
             mime_type="application/pdf", size_bytes=1024, file_path="storage/uploads/test.pdf", status="ready")
    db.add(f)
    db.commit()
    wf = WorkspaceFile(workspace_id=seed_engineering_workspace.id, file_id=f.id)
    db.add(wf)
    db.commit()
    return f


@pytest.fixture
def seed_general_file(db, seed_users, seed_general_workspace):
    f = File(owner_user_id=seed_users["alice"].id, filename="gen.pdf", file_type="pdf",
             mime_type="application/pdf", size_bytes=512, file_path="storage/uploads/gen.pdf", status="ready")
    db.add(f)
    db.commit()
    wf = WorkspaceFile(workspace_id=seed_general_workspace.id, file_id=f.id)
    db.add(wf)
    db.commit()
    return f


@pytest.fixture
def seed_file_profile(db, seed_engineering_workspace, seed_file, seed_users):
    fp = FileProfile(
        file_id=seed_file.id, workspace_id=seed_engineering_workspace.id,
        owner_user_id=seed_users["alice"].id, profile_version=1, status="ready",
        file_category="document", suggested_role="reference_document",
    )
    db.add(fp)
    db.commit()
    return fp


@pytest.fixture
def seed_confirmed_brief(db, seed_users, seed_engineering_workspace):
    """创建一个已确认的 ReviewBrief。"""
    return _make_confirmed_brief(db, seed_users["alice"].id, seed_engineering_workspace.id)


def _make_confirmed_brief(db, owner_id, ws_id):
    intent = InterpretedIntent(
        objectives=["检查投标文件一致性"],
        required_check_types=["required_field", "cross_file_equal", "numeric_threshold",
                              "date_order", "document_presence", "evidence_required"],
        excluded_check_types=[],
        excluded_scopes=[],
        priority_fields=["bid_response.project_name"],
        output_requirements=["high_risk_requires_evidence", "group_by_severity"],
        clarification_questions=[],
        unsupported_requests=[],
    )
    data = ReviewBriefCreate(raw_requirements="检查投标文件一致性", interpreted=intent)
    brief = create_review_brief(db, workspace_id=ws_id, owner_user_id=owner_id, data=data)
    return confirm_review_brief(db, brief_id=brief.id, owner_user_id=owner_id)


# ── 规则加载（保留，无变更）─────────────────────────────────────


class TestRuleLoading:
    def test_valid_yaml_loads(self, rule_pack):
        assert rule_pack.pack_id == "engineering_bid_review_v1"
        assert rule_pack.version == "1.1.0"
        assert len(rule_pack.rules) == 14
        types = {r.type for r in rule_pack.rules}
        assert types == {"required_field", "cross_file_equal", "numeric_threshold", "date_order", "document_presence", "evidence_required"}

    def test_unknown_pack_rejected(self):
        with pytest.raises(RuleLoadError, match="不支持的规则包"):
            load_rule_pack("nonexistent_pack")

    def test_hash_stable(self, rule_pack):
        snapshot = compute_rule_snapshot(rule_pack)
        h1 = compute_rule_pack_hash(snapshot)
        h2 = compute_rule_pack_hash(snapshot)
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_changes_with_content(self, rule_pack):
        snapshot1 = compute_rule_snapshot(rule_pack)
        h1 = compute_rule_pack_hash(snapshot1)
        modified = snapshot1.replace("engineering_bid_review_v1", "engineering_bid_review_v2")
        h2 = compute_rule_pack_hash(modified)
        assert h1 != h2


# ── 六类规则确定性执行（保留）───────────────────────────────────


def _make_input(fields: dict, doc_roles: dict | None = None) -> StructuredReviewInput:
    return StructuredReviewInput(
        fields={k: StructuredFieldValue(value=v) for k, v in fields.items()},
        document_roles=doc_roles or {},
    )


class TestRequiredField:
    def test_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-REQ-001")
        assert execute_rule(rule, _make_input({"bid_response.project_name": "某某大桥检测项目"})) is None

    def test_fail_empty(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-REQ-001")
        r = execute_rule(rule, _make_input({"bid_response.project_name": ""}))
        assert r is not None and r["passed"] is False

    def test_fail_absent(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-REQ-001")
        assert execute_rule(rule, _make_input({})) is not None


class TestCrossFileEqual:
    def test_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-EQ-001")
        assert execute_rule(rule, _make_input({
            "bid_response.project_name": "某某大桥检测",
            "personnel_equipment_data.project_name": "某某大桥检测",
        })) is None

    def test_fail(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-EQ-001")
        r = execute_rule(rule, _make_input({
            "bid_response.project_name": "某某大桥检测",
            "personnel_equipment_data.project_name": "某某大桥检测项目",
        }))
        assert r is not None and r["passed"] is False


class TestNumericThreshold:
    def test_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-NUM-001")
        assert execute_rule(rule, _make_input({"personnel_equipment_data.total_personnel": 8})) is None

    def test_fail(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-NUM-001")
        r = execute_rule(rule, _make_input({"personnel_equipment_data.total_personnel": 3}))
        assert r is not None and r["passed"] is False


class TestDateOrder:
    def test_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-DATE-001")
        assert execute_rule(rule, _make_input({"qualification_attachment.expiry_date": "2028-06-30"})) is None

    def test_fail(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-DATE-001")
        r = execute_rule(rule, _make_input({"qualification_attachment.expiry_date": "2027-01-01"}))
        assert r is not None and r["passed"] is False


class TestDocumentPresence:
    def test_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-DOC-001")
        assert execute_rule(rule, _make_input({}, {"qualification_attachment": [1, 2]})) is None

    def test_fail(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-DOC-001")
        r = execute_rule(rule, _make_input({}, {"bid_response": [1]}))
        assert r is not None and r["passed"] is False


class TestEvidenceRequired:
    def test_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-EVD-001")
        inp = StructuredReviewInput(fields={
            "bid_response.leader_name": StructuredFieldValue(value="张三", evidence_ids=[1]),
            "personnel_equipment_data.leader_name": StructuredFieldValue(value="张三", evidence_ids=[2]),
        })
        assert execute_rule(rule, inp) is None

    def test_fail(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-EVD-001")
        inp = StructuredReviewInput(fields={
            "bid_response.leader_name": StructuredFieldValue(value="张三", evidence_ids=[]),
        })
        r = execute_rule(rule, inp)
        assert r is not None and r["passed"] is False


class TestNewDeviceRules:
    """v1.1.0 新增的两条设备规则。"""

    def test_syn_num_003_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-NUM-003")
        assert execute_rule(rule, _make_input({"personnel_equipment_data.total_equipment": 5})) is None

    def test_syn_num_003_fail(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-NUM-003")
        r = execute_rule(rule, _make_input({"personnel_equipment_data.total_equipment": 3}))
        assert r is not None and r["passed"] is False

    def test_syn_date_003_pass(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-DATE-003")
        assert execute_rule(rule, _make_input({"personnel_equipment_data.earliest_calibration_expiry": "2028-06-30"})) is None

    def test_syn_date_003_fail(self, rule_pack):
        rule = next(r for r in rule_pack.rules if r.rule_id == "SYN-DATE-003")
        r = execute_rule(rule, _make_input({"personnel_equipment_data.earliest_calibration_expiry": "2026-12-31"}))
        assert r is not None and r["passed"] is False


class TestExecuteAllRules:
    def test_all_executed(self, rule_pack):
        inp = StructuredReviewInput(
            fields={
                "bid_response.project_name": StructuredFieldValue(value="某某大桥检测"),
                "personnel_equipment_data.project_name": StructuredFieldValue(value="某某大桥检测"),
                "personnel_equipment_data.total_personnel": StructuredFieldValue(value=8),
                "personnel_equipment_data.leader_name": StructuredFieldValue(value="张三", evidence_ids=[1]),
                "bid_response.leader_name": StructuredFieldValue(value="张三", evidence_ids=[2]),
                "bid_response.leader_cert_number": StructuredFieldValue(value="CERT-2024-00123"),
                "personnel_equipment_data.leader_cert_number": StructuredFieldValue(value="CERT-2024-00123"),
                "bid_response.total_price": StructuredFieldValue(value=1500000),
                "qualification_attachment.expiry_date": StructuredFieldValue(value="2028-12-31"),
                "bid_response.submission_date": StructuredFieldValue(value="2026-08-15"),
                "qualification_attachment.cert_number": StructuredFieldValue(value="CERT-2024-00123", evidence_ids=[3]),
            },
            document_roles={"qualification_attachment": [1], "personnel_equipment_data": [2]},
        )
        results = execute_all_rules(rule_pack.rules, inp)
        assert isinstance(results, list)


# ── ReviewBrief ─────────────────────────────────────────────────


class TestReviewBrief:
    def test_engineering_create(self, db, seed_users, seed_engineering_workspace):
        intent = InterpretedIntent(
            objectives=["检查投标文件一致性"],
            required_check_types=["required_field", "cross_file_equal"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=["group_by_severity"],
            clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="检查投标文件一致性", interpreted=intent)
        brief = create_review_brief(
            db, workspace_id=seed_engineering_workspace.id,
            owner_user_id=seed_users["alice"].id, data=data,
        )
        assert brief.id is not None
        assert brief.version == 1
        assert brief.status == "draft"

    def test_general_rejected(self, db, seed_users, seed_general_workspace):
        intent = InterpretedIntent(
            objectives=["检查投标文件一致性"],
            required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[],
            clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="检查投标文件一致性", interpreted=intent)
        with pytest.raises(BriefServiceError, match="仅 engineering"):
            create_review_brief(
                db, workspace_id=seed_general_workspace.id,
                owner_user_id=seed_users["alice"].id, data=data,
            )

    def test_cross_user_rejected(self, db, seed_users, seed_engineering_workspace):
        intent = InterpretedIntent(
            objectives=["检查投标文件一致性"],
            required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[],
            clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="检查投标文件一致性", interpreted=intent)
        with pytest.raises(BriefServiceError, match="不存在或无权"):
            create_review_brief(
                db, workspace_id=seed_engineering_workspace.id,
                owner_user_id=seed_users["bob"].id, data=data,
            )

    def test_version_increments(self, db, seed_users, seed_engineering_workspace):
        intent = InterpretedIntent(
            objectives=["检查投标文件一致性"],
            required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[],
            clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="v1", interpreted=intent)
        b1 = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data)
        assert b1.version == 1
        data2 = ReviewBriefCreate(raw_requirements="v2", interpreted=intent)
        b2 = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data2)
        assert b2.version == 2

    def test_confirm_supersedes_old(self, db, seed_users, seed_engineering_workspace):
        intent = InterpretedIntent(
            objectives=["检查投标文件一致性"],
            required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[],
            clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="v1", interpreted=intent)
        b1 = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data)
        c1 = confirm_review_brief(db, brief_id=b1.id, owner_user_id=seed_users["alice"].id)
        assert c1.status == "confirmed"

        data2 = ReviewBriefCreate(raw_requirements="v2", interpreted=intent)
        b2 = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data2)
        c2 = confirm_review_brief(db, brief_id=b2.id, owner_user_id=seed_users["alice"].id)
        assert c2.status == "confirmed"
        # 旧版本变为 superseded
        db.refresh(c1)
        assert c1.status == "superseded"

    def test_clarification_blocks_confirm(self, db, seed_users, seed_engineering_workspace):
        intent = InterpretedIntent(
            objectives=["检查投标文件一致性"],
            required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[],
            clarification_questions=["需要确认招标范围"],
            unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="检查", interpreted=intent)
        brief = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data)
        assert brief.status == "needs_clarification"
        with pytest.raises(BriefServiceError, match="澄清"):
            confirm_review_brief(db, brief_id=brief.id, owner_user_id=seed_users["alice"].id)

    def test_unknown_check_type_rejected(self, db, seed_users, seed_engineering_workspace):
        with pytest.raises(ValueError):
            InterpretedIntent(
                objectives=["检查"],
                required_check_types=["bad_type"],
                excluded_check_types=[], excluded_scopes=[], priority_fields=[],
                output_requirements=[],
                clarification_questions=[], unsupported_requests=[],
            )

    def test_required_excluded_conflict(self, db, seed_users, seed_engineering_workspace):
        intent = InterpretedIntent(
            objectives=["检查"],
            required_check_types=["required_field", "cross_file_equal"],
            excluded_check_types=["required_field"],
            excluded_scopes=[], priority_fields=[],
            output_requirements=[],
            clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="检查", interpreted=intent)
        with pytest.raises(BriefServiceError, match="冲突"):
            create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data)

    def test_forbidden_control_field_rejected(self):
        with pytest.raises(ValueError):
            InterpretedIntent(
                objectives=["执行 shell 命令"],
                required_check_types=["required_field"],
                excluded_check_types=[], excluded_scopes=[], priority_fields=[],
                output_requirements=[],
                clarification_questions=[], unsupported_requests=[],
            )

    def test_hash_stable(self, db, seed_users, seed_engineering_workspace):
        intent = InterpretedIntent(
            objectives=["检查投标文件一致性"],
            required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[],
            clarification_questions=[], unsupported_requests=[],
        )
        data1 = ReviewBriefCreate(raw_requirements="检查", interpreted=intent)
        b1 = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data1)
        data2 = ReviewBriefCreate(raw_requirements="检查", interpreted=intent)
        b2 = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data2)
        assert b1.content_hash == b2.content_hash


# ── ReviewRun ⇔ Brief 绑定 ──────────────────────────────────────


class TestReviewRunBriefBinding:
    def test_confirmed_brief_binds(self, db, seed_users, seed_engineering_workspace, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        assert run.review_brief_id == seed_confirmed_brief.id
        assert run.review_brief_version == seed_confirmed_brief.version
        assert run.review_brief_hash is not None
        assert run.review_brief_snapshot_json is not None

    def test_draft_rejected(self, db, seed_users, seed_engineering_workspace, rule_pack):
        intent = InterpretedIntent(
            objectives=["检查"], required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[], clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="检查", interpreted=intent)
        brief = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data)
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        with pytest.raises(ReviewServiceError, match="confirmed"):
            create_review_run(
                db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
                rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
                review_brief_id=brief.id,
            )

    def test_cross_workspace_rejected(self, db, seed_users, seed_engineering_workspace, rule_pack):
        # 另一个 engineering workspace
        ws2 = Workspace(owner_user_id=seed_users["alice"].id, name="工程2", workspace_type="engineering",
                        review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws2)
        db.commit()
        brief2 = _make_confirmed_brief(db, seed_users["alice"].id, ws2.id)
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        with pytest.raises(ReviewServiceError, match="不存在或不属于"):
            create_review_run(
                db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
                rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
                review_brief_id=brief2.id,
            )

    def test_new_brief_version_does_not_change_history(self, db, seed_users, seed_engineering_workspace, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        original_snapshot = run.review_brief_snapshot_json

        # 创建新版 Brief 并确认（旧 brief 变 superseded）
        intent = InterpretedIntent(
            objectives=["v2检查"], required_check_types=["required_field"],
            excluded_check_types=[], excluded_scopes=[], priority_fields=[],
            output_requirements=[], clarification_questions=[], unsupported_requests=[],
        )
        data = ReviewBriefCreate(raw_requirements="v2检查", interpreted=intent)
        new_brief = create_review_brief(db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id, data=data)
        confirm_review_brief(db, brief_id=new_brief.id, owner_user_id=seed_users["alice"].id)

        # 历史 Run 快照不变
        db.refresh(run)
        assert run.review_brief_snapshot_json == original_snapshot


# ── Evidence 真实校验 ──────────────────────────────────────────


class TestEvidenceRealValidation:
    def test_real_file_succeeds(self, db, seed_users, seed_engineering_workspace, seed_file, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        ev = EvidenceCreate(file_id=seed_file.id, locator_type="pdf_page", page_number=5,
                            quote="证据内容", parser_name="p", parser_version="1")
        record = create_evidence(db, review_run_id=run.id, workspace_id=seed_engineering_workspace.id,
                                 owner_user_id=seed_users["alice"].id, evidence=ev)
        assert record.id is not None
        assert len(record.content_hash) == 64

    def test_nonexistent_file_rejected(self, db, seed_users, seed_engineering_workspace, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        ev = EvidenceCreate(file_id=99999, locator_type="pdf_page", page_number=1,
                            quote="test", parser_name="p", parser_version="1")
        with pytest.raises(ReviewServiceError, match="不存在"):
            create_evidence(db, review_run_id=run.id, workspace_id=seed_engineering_workspace.id,
                            owner_user_id=seed_users["alice"].id, evidence=ev)

    def test_file_not_in_workspace_rejected(self, db, seed_users, seed_engineering_workspace, rule_pack, seed_confirmed_brief):
        # 创建 File 但不关联到 workspace
        f = File(owner_user_id=seed_users["alice"].id, filename="orphan.pdf", file_type="pdf",
                 mime_type="application/pdf", size_bytes=100, file_path="storage/uploads/orphan.pdf", status="ready")
        db.add(f)
        db.commit()
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        ev = EvidenceCreate(file_id=f.id, locator_type="pdf_page", page_number=1,
                            quote="test", parser_name="p", parser_version="1")
        with pytest.raises(ReviewServiceError, match="未关联"):
            create_evidence(db, review_run_id=run.id, workspace_id=seed_engineering_workspace.id,
                            owner_user_id=seed_users["alice"].id, evidence=ev)

    def test_cross_user_file_rejected(self, db, seed_users, seed_engineering_workspace, seed_file, rule_pack, seed_confirmed_brief):
        # bob 拥有自己的 engineering workspace、file、brief、run
        bob_ws = Workspace(owner_user_id=seed_users["bob"].id, name="Bob工程", workspace_type="engineering",
                           review_template_key="engineering_bid_review_v1", status="active")
        db.add(bob_ws)
        db.commit()
        bob_brief = _make_confirmed_brief(db, seed_users["bob"].id, bob_ws.id)
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        bob_run = create_review_run(
            db, workspace_id=bob_ws.id, owner_user_id=seed_users["bob"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=bob_brief.id,
        )
        # alice 的文件 — bob 尝试用在自己的审查中
        ev = EvidenceCreate(file_id=seed_file.id, locator_type="pdf_page", page_number=1,
                            quote="test", parser_name="p", parser_version="1")
        with pytest.raises(ReviewServiceError, match="不属于当前用户"):
            create_evidence(db, review_run_id=bob_run.id, workspace_id=bob_ws.id,
                            owner_user_id=seed_users["bob"].id, evidence=ev)

    def test_review_run_scope_mismatch(self, db, seed_users, seed_engineering_workspace, seed_file, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        ev = EvidenceCreate(file_id=seed_file.id, locator_type="pdf_page", page_number=1,
                            quote="test", parser_name="p", parser_version="1")
        # 用错误的 workspace_id
        with pytest.raises(ReviewServiceError, match="归属不匹配"):
            create_evidence(db, review_run_id=run.id, workspace_id=99999,
                            owner_user_id=seed_users["alice"].id, evidence=ev)

    def test_locator_page_number_zero_rejected(self):
        with pytest.raises(ValueError, match="≥ 1"):
            EvidenceCreate(file_id=1, locator_type="pdf_page", page_number=0,
                           quote="test", parser_name="p", parser_version="1")

    def test_locator_chunk_id_zero_rejected(self):
        with pytest.raises(ValueError, match="≥ 1"):
            EvidenceCreate(file_id=1, locator_type="text_chunk", chunk_id=0,
                           quote="test", parser_name="p", parser_version="1")

    def test_locator_empty_sheet_rejected(self):
        with pytest.raises(ValueError, match="非空 sheet_name"):
            EvidenceCreate(file_id=1, locator_type="spreadsheet_cell", sheet_name="   ",
                           cell_range="A1", quote="test", parser_name="p", parser_version="1")

    # Finding 绑定仍正常
    def test_finding_binding_still_works(self, db, seed_users, seed_engineering_workspace, seed_file, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        ev = EvidenceCreate(file_id=seed_file.id, locator_type="pdf_page", page_number=1,
                            quote="证据内容", parser_name="p", parser_version="1")
        evidence = create_evidence(db, review_run_id=run.id, workspace_id=seed_engineering_workspace.id,
                                   owner_user_id=seed_users["alice"].id, evidence=ev)
        finding = create_review_finding(
            db, review_run_id=run.id, workspace_id=seed_engineering_workspace.id,
            owner_user_id=seed_users["alice"].id, issue_code="TEST", title="测试",
            category="一致性", severity="high", conclusion="结论", suggestion="建议",
            rule_id="SYN-EQ-001", rule_version="1.0", evidence_ids=[evidence.id],
        )
        assert finding.id is not None


# ── 人工操作（保留，适配新 API）─────────────────────────────────


class TestReviewActions:
    @pytest.fixture
    def run_and_evidence(self, db, seed_users, seed_engineering_workspace, seed_file, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        ev = EvidenceCreate(file_id=seed_file.id, locator_type="pdf_page", page_number=1,
                            quote="证据内容", parser_name="p", parser_version="1")
        evidence = create_evidence(db, review_run_id=run.id, workspace_id=seed_engineering_workspace.id,
                                   owner_user_id=seed_users["alice"].id, evidence=ev)
        finding = create_review_finding(
            db, review_run_id=run.id, workspace_id=seed_engineering_workspace.id,
            owner_user_id=seed_users["alice"].id, issue_code="SYN-EQ-001", title="项目名称不一致",
            category="跨文件一致性", severity="high", conclusion="两处项目名称不一致",
            suggestion="核对并统一", rule_id="SYN-EQ-001", rule_version="1.0",
            evidence_ids=[evidence.id],
        )
        return run, evidence, finding

    def test_confirm(self, db, seed_users, run_and_evidence):
        _, _, finding = run_and_evidence
        updated, action = execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["alice"].id, action_type="confirm", review_note="已核实")
        assert updated.status == "confirmed"
        assert action.action_type == "confirm"

    def test_reject(self, db, seed_users, run_and_evidence):
        _, _, finding = run_and_evidence
        updated, _ = execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["alice"].id, action_type="reject")
        assert updated.status == "rejected"

    def test_modify_preserves_before_after(self, db, seed_users, run_and_evidence):
        _, _, finding = run_and_evidence
        orig = finding.conclusion
        updated, action = execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["alice"].id, action_type="modify", modified_conclusion="新结论")
        assert updated.status == "modified"
        assert updated.conclusion == "新结论"
        assert json.loads(action.before_json)["conclusion"] == orig
        assert json.loads(action.after_json)["conclusion"] == "新结论"

    def test_resolve(self, db, seed_users, run_and_evidence):
        _, _, finding = run_and_evidence
        updated, _ = execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["alice"].id, action_type="resolve")
        assert updated.status == "resolved"

    def test_actions_append_in_order(self, db, seed_users, run_and_evidence):
        _, _, finding = run_and_evidence
        execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["alice"].id, action_type="confirm", review_note="第一步")
        execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["alice"].id, action_type="reject", review_note="第二步")
        actions = list_actions_for_finding(db, finding.id, seed_users["alice"].id)
        assert len(actions) == 2
        assert actions[0].review_note == "第一步"
        assert actions[1].review_note == "第二步"

    def test_other_user_rejected(self, db, seed_users, run_and_evidence):
        _, _, finding = run_and_evidence
        with pytest.raises(ReviewServiceError, match="不存在或无权"):
            execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["bob"].id, action_type="confirm")

    def test_invalid_action_rejected(self, db, seed_users, run_and_evidence):
        _, _, finding = run_and_evidence
        with pytest.raises(ReviewServiceError, match="action_type"):
            execute_review_action(db, finding_id=finding.id, owner_user_id=seed_users["alice"].id, action_type="delete")


# ── ReviewRun 生命周期（适配新 API）────────────────────────────


class TestReviewRunLifecycle:
    def test_lifecycle(self, db, seed_users, seed_engineering_workspace, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        assert run.status == "pending"
        started = start_review_run(db, run)
        assert started.status == "running"
        assert started.started_at is not None
        completed = complete_review_run(db, run)
        assert completed.status == "completed"

    def test_fail(self, db, seed_users, seed_engineering_workspace, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        failed = fail_review_run(db, run, "TEST", "失败")
        assert failed.status == "failed"
        assert failed.error_code == "TEST"


# ── 产品隔离 ────────────────────────────────────────────────────


class TestProductIsolation:
    def test_engineering_can_run(self, db, seed_users, seed_engineering_workspace, rule_pack, seed_confirmed_brief):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        run = create_review_run(
            db, workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
            review_brief_id=seed_confirmed_brief.id,
        )
        assert run.id is not None

    def test_general_rejected(self, db, seed_users, seed_general_workspace, rule_pack):
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        with pytest.raises(ReviewServiceError, match="仅 engineering"):
            create_review_run(
                db, workspace_id=seed_general_workspace.id, owner_user_id=seed_users["alice"].id,
                rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
                review_brief_id=1,
            )

    def test_engineering_without_template_rejected(self, db, seed_users, rule_pack):
        ws = Workspace(owner_user_id=seed_users["alice"].id, name="无模板", workspace_type="engineering",
                       review_template_key=None, status="active")
        db.add(ws)
        db.commit()
        snapshot = compute_rule_snapshot(rule_pack)
        h = compute_rule_pack_hash(snapshot)
        with pytest.raises(ReviewServiceError, match="未设置工程审查模板"):
            create_review_run(
                db, workspace_id=ws.id, owner_user_id=seed_users["alice"].id,
                rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=h,
                review_brief_id=1,
            )

    def test_general_cannot_set_engineering_template_db(self, db, seed_general_workspace):
        """新约束：general + engineering_bid_review_v1 在数据库层被拒绝。"""
        db.expire_all()
        with pytest.raises(Exception):
            db.execute(text(f"UPDATE workspaces SET review_template_key = 'engineering_bid_review_v1' WHERE id = {seed_general_workspace.id}"))
            db.commit()

    def test_engineering_template_passes(self, db, seed_users):
        ws = Workspace(owner_user_id=seed_users["alice"].id, name="工程", workspace_type="engineering",
                       review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws)
        db.commit()  # 不抛异常
        assert ws.id is not None


# ── 工程角色真实服务集成 ────────────────────────────────────────


class TestEngineeringRolesRealService:
    def test_engineering_can_confirm_engineering_role(self, db, seed_users, seed_engineering_workspace, seed_file, seed_file_profile):
        """engineering 工作区可以通过真实服务确认工程角色。"""
        result = update_profile_confirmation(
            db, workspace_id=seed_engineering_workspace.id, file_id=seed_file.id,
            owner_user_id=seed_users["alice"].id, confirmed_role="tender_requirement",
            custom_role=None, user_tags=None,
        )
        assert result.confirmed_role == "tender_requirement"

    def test_general_rejects_engineering_role(self, db, seed_users, seed_general_workspace, seed_general_file):
        """general 工作区确认工程角色被拒绝。"""
        fp = FileProfile(file_id=seed_general_file.id, workspace_id=seed_general_workspace.id,
                         owner_user_id=seed_users["alice"].id, profile_version=1, status="ready",
                         file_category="document", suggested_role="reference_document")
        db.add(fp)
        db.commit()
        with pytest.raises(FileUnderstandingError, match="仅限 engineering"):
            update_profile_confirmation(
                db, workspace_id=seed_general_workspace.id, file_id=seed_general_file.id,
                owner_user_id=seed_users["alice"].id, confirmed_role="tender_requirement",
                custom_role=None, user_tags=None,
            )

    def test_engineering_can_still_use_general_role(self, db, seed_users, seed_engineering_workspace, seed_file, seed_file_profile):
        """engineering 工作区仍可使用原有通用角色。"""
        result = update_profile_confirmation(
            db, workspace_id=seed_engineering_workspace.id, file_id=seed_file.id,
            owner_user_id=seed_users["alice"].id, confirmed_role="reference_document",
            custom_role=None, user_tags=None,
        )
        assert result.confirmed_role == "reference_document"

    def test_general_can_confirm_general_role(self, db, seed_users, seed_general_workspace, seed_general_file):
        """general 工作区可以确认通用角色（原有行为不退步）。"""
        fp = FileProfile(file_id=seed_general_file.id, workspace_id=seed_general_workspace.id,
                         owner_user_id=seed_users["alice"].id, profile_version=1, status="ready",
                         file_category="document", suggested_role="reference_document")
        db.add(fp)
        db.commit()
        result = update_profile_confirmation(
            db, workspace_id=seed_general_workspace.id, file_id=seed_general_file.id,
            owner_user_id=seed_users["alice"].id, confirmed_role="reference_document",
            custom_role=None, user_tags=None,
        )
        assert result.confirmed_role == "reference_document"


# ── 工程关系真实服务集成 ────────────────────────────────────────


class TestEngineeringRelationsRealService:
    @pytest.fixture
    def two_engineering_files(self, db, seed_users, seed_engineering_workspace):
        f1 = File(owner_user_id=seed_users["alice"].id, filename="a.pdf", file_type="pdf",
                  mime_type="application/pdf", size_bytes=100, file_path="storage/uploads/a.pdf", status="ready")
        f2 = File(owner_user_id=seed_users["alice"].id, filename="b.pdf", file_type="pdf",
                  mime_type="application/pdf", size_bytes=200, file_path="storage/uploads/b.pdf", status="ready")
        db.add_all([f1, f2])
        db.commit()
        wf1 = WorkspaceFile(workspace_id=seed_engineering_workspace.id, file_id=f1.id)
        wf2 = WorkspaceFile(workspace_id=seed_engineering_workspace.id, file_id=f2.id)
        db.add_all([wf1, wf2])
        db.commit()
        # 创建 suggested 关系
        rel = FileRelation(
            workspace_id=seed_engineering_workspace.id, owner_user_id=seed_users["alice"].id,
            source_file_id=f1.id, target_file_id=f2.id, relation_type="same_dataset",
            direction="bidirectional", confidence=0.8, suggested_by="deterministic", status="suggested",
        )
        db.add(rel)
        db.commit()
        return {"f1": f1, "f2": f2, "rel": rel}

    def test_engineering_can_use_engineering_relation(self, db, seed_users, seed_engineering_workspace, two_engineering_files):
        """engineering 工作区可以通过真实流程确认工程关系。"""
        result = mutate_file_relation(
            db, workspace_id=seed_engineering_workspace.id, relation_id=two_engineering_files["rel"].id,
            owner_user_id=seed_users["alice"].id, action="replace",
            relation_type="constrains", custom_relation_type=None, user_note=None,
        )
        assert result.relation_type == "constrains"
        assert result.status == "confirmed"

    def test_general_rejects_engineering_relation(self, db, seed_users, seed_general_workspace, seed_general_file):
        """general 工作区使用工程关系被拒绝。"""
        f2 = File(owner_user_id=seed_users["alice"].id, filename="b.pdf", file_type="pdf",
                  mime_type="application/pdf", size_bytes=200, file_path="storage/uploads/b.pdf", status="ready")
        db.add(f2)
        db.commit()
        wf2 = WorkspaceFile(workspace_id=seed_general_workspace.id, file_id=f2.id)
        db.add(wf2)
        db.commit()
        rel = FileRelation(
            workspace_id=seed_general_workspace.id, owner_user_id=seed_users["alice"].id,
            source_file_id=seed_general_file.id, target_file_id=f2.id, relation_type="same_dataset",
            direction="bidirectional", confidence=0.8, suggested_by="deterministic", status="suggested",
        )
        db.add(rel)
        db.commit()
        with pytest.raises(FileRelationError, match="仅限 engineering"):
            mutate_file_relation(
                db, workspace_id=seed_general_workspace.id, relation_id=rel.id,
                owner_user_id=seed_users["alice"].id, action="replace",
                relation_type="constrains", custom_relation_type=None, user_note=None,
            )

    def test_general_relation_still_works(self, db, seed_users, seed_general_workspace, seed_general_file):
        """general 原有关系行为不退步。"""
        f2 = File(owner_user_id=seed_users["alice"].id, filename="b.pdf", file_type="pdf",
                  mime_type="application/pdf", size_bytes=200, file_path="storage/uploads/b.pdf", status="ready")
        db.add(f2)
        db.commit()
        wf2 = WorkspaceFile(workspace_id=seed_general_workspace.id, file_id=f2.id)
        db.add(wf2)
        db.commit()
        rel = FileRelation(
            workspace_id=seed_general_workspace.id, owner_user_id=seed_users["alice"].id,
            source_file_id=seed_general_file.id, target_file_id=f2.id, relation_type="same_dataset",
            direction="bidirectional", confidence=0.8, suggested_by="deterministic", status="suggested",
        )
        db.add(rel)
        db.commit()
        result = mutate_file_relation(
            db, workspace_id=seed_general_workspace.id, relation_id=rel.id,
            owner_user_id=seed_users["alice"].id, action="confirm",
            relation_type=None, custom_relation_type=None, user_note=None,
        )
        assert result.status == "confirmed"
