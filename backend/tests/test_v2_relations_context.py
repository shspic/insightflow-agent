import dataclasses
import json
from pathlib import Path

import fitz
from sqlalchemy import func, select

from app.core.config import settings
from app.models.file import File
from app.models.file_relation import FileRelation
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.file_relation_service import (
    FileRelationError,
    discover_file_relations,
    list_file_relations,
    mutate_file_relation,
)
from app.services.file_understanding_service import (
    understand_file,
    update_profile_confirmation,
)
from app.services.workspace_context_service import build_workspace_context


def create_owner_workspace(db_session, username: str = "relations.user"):
    user = User(
        username=username,
        password_hash="test-hash",
        role="user",
        status="active",
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    workspace = Workspace(
        owner_user_id=user.id,
        name="关系测试",
        description="比较岗位并核对规则",
        status="active",
    )
    db_session.add(workspace)
    db_session.commit()
    return user, workspace


def add_file(
    db_session,
    user,
    workspace,
    path: Path,
    *,
    file_type: str,
    mime_type: str,
):
    file_record = File(
        owner_user_id=user.id,
        filename=path.name,
        file_type=file_type,
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        file_path=str(path),
        status="uploaded",
    )
    db_session.add(file_record)
    db_session.flush()
    db_session.add(WorkspaceFile(workspace_id=workspace.id, file_id=file_record.id))
    db_session.commit()
    understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    return file_record


def test_table_relation_discovery_rerun_and_confirmed_decision_are_stable(
    db_session,
    tmp_path,
):
    user, workspace = create_owner_workspace(db_session)
    first_path = tmp_path / "岗位_北京_2025.csv"
    second_path = tmp_path / "岗位_上海_2026.csv"
    first_path.write_text("job_id,company,salary\n1,A,20\n2,B,25\n", encoding="utf-8")
    second_path.write_text("job_id,company,salary\n3,C,21\n4,D,26\n", encoding="utf-8")
    first = add_file(
        db_session,
        user,
        workspace,
        first_path,
        file_type="csv",
        mime_type="text/csv",
    )
    second = add_file(
        db_session,
        user,
        workspace,
        second_path,
        file_type="csv",
        mime_type="text/csv",
    )

    discovered = discover_file_relations(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    assert discovered.created_count == 1
    relation = discovered.relations[0]
    assert relation.relation_type == "continuation"
    assert relation.status == "suggested"
    assert relation.evidence["column_similarity"] == 1.0

    confirmed = mutate_file_relation(
        db_session,
        workspace_id=workspace.id,
        relation_id=relation.id,
        owner_user_id=user.id,
        action="confirm",
        relation_type=None,
        custom_relation_type=None,
        user_note="确认是连续年份岗位数据",
    )
    assert confirmed.status == "confirmed"
    rerun = discover_file_relations(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        file_ids=[first.id, second.id],
    )
    assert rerun.created_count == 0
    assert rerun.preserved_user_decision_count == 1
    assert db_session.scalar(
        select(func.count()).select_from(FileRelation).where(
            FileRelation.workspace_id == workspace.id
        )
    ) == 1


def test_pdf_rule_and_image_ocr_relations_are_explainable(
    db_session,
    tmp_path,
    monkeypatch,
):
    from PIL import Image

    user, workspace = create_owner_workspace(db_session, "mixed.relations")
    table_path = tmp_path / "实验结果.csv"
    table_path.write_text("metric,score\naccuracy,92\nrecall,88\n", encoding="utf-8")
    table = add_file(
        db_session,
        user,
        workspace,
        table_path,
        file_type="csv",
        mime_type="text/csv",
    )

    pdf_path = tmp_path / "课程评分规则.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Scoring Rule\nmetric and score must be listed together.")
    document.save(pdf_path)
    document.close()
    pdf = add_file(
        db_session,
        user,
        workspace,
        pdf_path,
        file_type="pdf",
        mime_type="application/pdf",
    )

    image_path = tmp_path / "准确率截图.png"
    Image.new("RGB", (800, 500), color="white").save(image_path)
    monkeypatch.setattr(
        "app.services.file_understanding_service.extract_text_from_image",
        lambda record: {
            "status": "success",
            "engine": "mock",
            "text": "experiment metric accuracy score 92",
        },
    )
    image = add_file(
        db_session,
        user,
        workspace,
        image_path,
        file_type="png",
        mime_type="image/png",
    )

    result = discover_file_relations(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    relation_types = {relation.relation_type for relation in result.relations}
    assert "reference_rule" in relation_types
    assert "image_evidence" in relation_types
    rule_relation = next(
        relation for relation in result.relations if relation.relation_type == "reference_rule"
    )
    assert rule_relation.source_file_id == pdf.id
    assert rule_relation.target_file_id == table.id
    assert "metric" in rule_relation.evidence["matched_columns"]
    image_relations = [
        relation
        for relation in result.relations
        if relation.relation_type == "image_evidence"
    ]
    assert any(relation.source_file_id == image.id for relation in image_relations)


def test_low_confidence_and_cross_workspace_candidates_are_rejected(
    db_session,
    tmp_path,
):
    user, workspace = create_owner_workspace(db_session, "scope.owner")
    first_path = tmp_path / "alpha.csv"
    second_path = tmp_path / "unrelated.csv"
    first_path.write_text("a,b\n1,2\n", encoding="utf-8")
    second_path.write_text("x,y\n3,4\n", encoding="utf-8")
    first = add_file(
        db_session,
        user,
        workspace,
        first_path,
        file_type="csv",
        mime_type="text/csv",
    )
    second = add_file(
        db_session,
        user,
        workspace,
        second_path,
        file_type="csv",
        mime_type="text/csv",
    )
    result = discover_file_relations(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        file_ids=[first.id, second.id],
    )
    assert result.relations == []

    other_user, other_workspace = create_owner_workspace(db_session, "scope.other")
    other_path = tmp_path / "other.csv"
    other_path.write_text("a,b\n5,6\n", encoding="utf-8")
    other_file = add_file(
        db_session,
        other_user,
        other_workspace,
        other_path,
        file_type="csv",
        mime_type="text/csv",
    )
    try:
        discover_file_relations(
            db_session,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            file_ids=[first.id, other_file.id],
        )
    except FileRelationError as exc:
        assert exc.code == "INVALID_FILE_SCOPE"
    else:
        raise AssertionError("跨工作区或跨用户关系必须被拒绝")


def test_relation_reject_and_replace_preserve_audit_history(db_session, tmp_path):
    user, workspace = create_owner_workspace(db_session, "mutation.owner")
    first_path = tmp_path / "data_v1.csv"
    second_path = tmp_path / "data_v2.csv"
    first_path.write_text("id,value\n1,10\n", encoding="utf-8")
    second_path.write_text("id,value\n2,20\n", encoding="utf-8")
    first = add_file(
        db_session,
        user,
        workspace,
        first_path,
        file_type="csv",
        mime_type="text/csv",
    )
    second = add_file(
        db_session,
        user,
        workspace,
        second_path,
        file_type="csv",
        mime_type="text/csv",
    )
    relation = discover_file_relations(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        file_ids=[first.id, second.id],
    ).relations[0]
    rejected = mutate_file_relation(
        db_session,
        workspace_id=workspace.id,
        relation_id=relation.id,
        owner_user_id=user.id,
        action="reject",
        relation_type=None,
        custom_relation_type=None,
        user_note="不是同一批数据",
    )
    assert rejected.status == "rejected"
    corrected = mutate_file_relation(
        db_session,
        workspace_id=workspace.id,
        relation_id=rejected.id,
        owner_user_id=user.id,
        action="replace",
        relation_type="comparison",
        custom_relation_type=None,
        user_note="仅用于版本对比",
    )
    assert corrected.status == "confirmed"
    assert corrected.relation_type == "comparison"
    assert corrected.supersedes_relation_id == rejected.id
    db_session.refresh(rejected)
    assert rejected.status == "superseded"
    all_versions = list_file_relations(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        status_filter="superseded",
    )
    assert [item.id for item in all_versions] == [rejected.id]


def test_workspace_context_uses_confirmed_roles_relations_and_safe_limits(
    db_session,
    tmp_path,
    monkeypatch,
):
    user, workspace = create_owner_workspace(db_session, "context.owner")
    first_path = tmp_path / "岗位_北京.csv"
    second_path = tmp_path / "岗位_上海.csv"
    first_path.write_text("job_id,skill\n1,Python\n", encoding="utf-8")
    second_path.write_text("job_id,skill\n2,SQL\n", encoding="utf-8")
    first = add_file(
        db_session,
        user,
        workspace,
        first_path,
        file_type="csv",
        mime_type="text/csv",
    )
    second = add_file(
        db_session,
        user,
        workspace,
        second_path,
        file_type="csv",
        mime_type="text/csv",
    )
    update_profile_confirmation(
        db_session,
        workspace_id=workspace.id,
        file_id=first.id,
        owner_user_id=user.id,
        confirmed_role="primary_dataset",
        custom_role=None,
        user_tags=["优先"],
    )
    relation = discover_file_relations(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    ).relations[0]
    mutate_file_relation(
        db_session,
        workspace_id=workspace.id,
        relation_id=relation.id,
        owner_user_id=user.id,
        action="confirm",
        relation_type=None,
        custom_relation_type=None,
        user_note=None,
    )

    context = build_workspace_context(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        selected_file_ids=[first.id, second.id],
    )
    assert context.context_version == "2.03"
    assert context.selected_file_ids == [first.id, second.id]
    first_context = next(item for item in context.files if item["file_id"] == first.id)
    assert first_context["effective_role"] == "primary_dataset"
    assert first_context["role_source"] == "user"
    assert context.confirmed_relations
    serialized = context.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "file_path" not in serialized
    assert "LLM_API_KEY" not in serialized

    monkeypatch.setattr(
        "app.services.workspace_context_service.settings",
        dataclasses.replace(settings, workspace_context_max_files=1),
    )
    truncated = build_workspace_context(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    assert truncated.limits["truncated"] is True
    assert truncated.limits["included_file_count"] == 1
    assert truncated.selected_file_ids == [first.id]


def test_workspace_context_rejects_another_users_file(db_session, tmp_path):
    user, workspace = create_owner_workspace(db_session, "context.a")
    own_path = tmp_path / "own.csv"
    own_path.write_text("id\n1\n", encoding="utf-8")
    own_file = add_file(
        db_session,
        user,
        workspace,
        own_path,
        file_type="csv",
        mime_type="text/csv",
    )
    other_user, other_workspace = create_owner_workspace(db_session, "context.b")
    other_path = tmp_path / "private.csv"
    other_path.write_text("secret\n42\n", encoding="utf-8")
    other_file = add_file(
        db_session,
        other_user,
        other_workspace,
        other_path,
        file_type="csv",
        mime_type="text/csv",
    )
    try:
        build_workspace_context(
            db_session,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            selected_file_ids=[own_file.id, other_file.id],
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "INVALID_FILE_SCOPE"
    else:
        raise AssertionError("上下文不得包含其他用户文件")
