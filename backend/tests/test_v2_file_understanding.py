import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pandas as pd
from sqlalchemy import func, select

from app.models.audit_log import AuditLog
from app.models.file import File
from app.models.file_chunk import FileChunk
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.schemas.file_understanding import FileUnderstandOptions
from app.services.file_understanding_service import (
    FileUnderstandingError,
    get_latest_profile,
    get_workspace_file_association,
    profile_response,
    understand_file,
    update_profile_confirmation,
)


def add_owned_file(
    db_session,
    path: Path,
    *,
    file_type: str,
    mime_type: str,
    filename: str | None = None,
):
    user = User(
        username=f"user-{path.stem}-{file_type}",
        password_hash="test-hash",
        role="user",
        status="active",
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    workspace = Workspace(owner_user_id=user.id, name="文件理解测试", status="active")
    db_session.add(workspace)
    db_session.flush()
    file_record = File(
        owner_user_id=user.id,
        filename=filename or path.name,
        file_type=file_type,
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        file_path=str(path),
        status="uploaded",
    )
    db_session.add(file_record)
    db_session.flush()
    association = WorkspaceFile(workspace_id=workspace.id, file_id=file_record.id)
    db_session.add(association)
    db_session.commit()
    return user, workspace, file_record, association


def test_csv_profile_versions_and_confirmed_role_survive_rerun(db_session, tmp_path):
    path = tmp_path / "students.csv"
    path.write_text(
        "student_id,name,score,date\n1,Alice,95,2026-01-01\n2,Bob,,2026-01-02\n2,Bob,,2026-01-02\n",
        encoding="utf-8",
    )
    user, workspace, file_record, _ = add_owned_file(
        db_session,
        path,
        file_type="csv",
        mime_type="text/csv",
    )

    first = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        options=FileUnderstandOptions(use_deepseek=False),
    )
    assert first.status == "ready"
    assert first.profile_version == 1
    assert first.suggested_role == "primary_dataset"
    structure = json.loads(first.structure_json)
    table = structure["tables"][0]
    assert table["row_count"] == 3
    assert [column["name"] for column in table["columns"]] == [
        "student_id",
        "name",
        "score",
        "date",
    ]
    assert table["duplicate_rows"] == 1

    update_profile_confirmation(
        db_session,
        workspace_id=workspace.id,
        file_id=file_record.id,
        owner_user_id=user.id,
        confirmed_role="custom",
        custom_role="核心成绩数据",
        user_tags=["课程", "课程", "<script>", "  2026 春季  "],
    )
    second = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    assert second.profile_version == 2
    assert second.confirmed_role == "custom:核心成绩数据"
    association = get_workspace_file_association(
        db_session,
        workspace_id=workspace.id,
        file_id=file_record.id,
    )
    response = profile_response(second, association)
    assert response.effective_role == "custom:核心成绩数据"
    assert response.user_tags == ["课程", "2026 春季"]
    assert db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "file.profile.confirmation.update"
        )
    ) == 1


def test_multi_sheet_xlsx_profile(db_session, tmp_path):
    path = tmp_path / "jobs.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(
            {"job_id": [1, 2], "city": ["北京", "上海"], "salary": [20, 25]}
        ).to_excel(writer, sheet_name="岗位", index=False)
        pd.DataFrame(
            {"job_id": [1, 2], "status": ["已投递", "面试"]}
        ).to_excel(writer, sheet_name="投递", index=False)
    user, workspace, file_record, _ = add_owned_file(
        db_session,
        path,
        file_type="xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    profile = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    structure = json.loads(profile.structure_json)
    assert profile.status == "ready"
    assert structure["sheet_count"] == 2
    assert structure["sheet_names"] == ["岗位", "投递"]
    assert structure["tables"][0]["row_count"] == 2
    assert structure["tables"][1]["row_count"] == 2
    assert "job_id" in structure["tables"][0]["primary_key_candidates"]


def test_markdown_profile_and_chunks_are_safe(db_session, tmp_path):
    path = tmp_path / "notes.markdown"
    path.write_text(
        "# 求职记录\n\n## 岗位 A\n\n| 技能 | 要求 |\n| --- | --- |\n| Python | 熟练 |\n\n"
        "```python\nprint('不能执行')\n```\n\n[外链](https://example.com)\n"
        "<script>alert('x')</script>\n",
        encoding="utf-8",
    )
    user, workspace, file_record, _ = add_owned_file(
        db_session,
        path,
        file_type="markdown",
        mime_type="text/markdown",
    )

    profile = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    structure = json.loads(profile.structure_json)
    assert profile.status == "ready"
    assert profile.title == "求职记录"
    assert [item["level"] for item in structure["headings"]] == [1, 2]
    assert structure["code_block_count"] == 1
    assert structure["table_count"] == 1
    assert structure["link_count"] == 1
    assert structure["security"] == {
        "html_executed": False,
        "code_executed": False,
        "external_links_fetched": False,
        "local_references_followed": False,
    }
    chunks = db_session.scalars(
        select(FileChunk).where(
            FileChunk.file_id == file_record.id,
            FileChunk.source_type == "markdown",
        )
    ).all()
    assert chunks
    assert all(chunk.page_number is None for chunk in chunks)
    assert all(chunk.chunk_hash for chunk in chunks)


def test_pdf_text_profile_reuses_chunks_and_scanned_pdf_degrades(db_session, tmp_path):
    text_path = tmp_path / "rules.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "1 Course Rules\nScore must be at least 60.")
    document.save(text_path)
    document.close()
    user, workspace, file_record, _ = add_owned_file(
        db_session,
        text_path,
        file_type="pdf",
        mime_type="application/pdf",
    )
    profile = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    structure = json.loads(profile.structure_json)
    assert profile.status == "ready"
    assert structure["page_count"] == 1
    assert structure["chunk_count"] >= 1
    assert structure["citation_capability"]["page_numbers"] is True

    scan_path = tmp_path / "scan.pdf"
    scan_document = fitz.open()
    scan_document.new_page()
    scan_document.save(scan_path)
    scan_document.close()
    scan_user, scan_workspace, scan_file, _ = add_owned_file(
        db_session,
        scan_path,
        file_type="pdf",
        mime_type="application/pdf",
        filename="scan.pdf",
    )
    scan_profile = understand_file(
        db_session,
        file_id=scan_file.id,
        workspace_id=scan_workspace.id,
        owner_user_id=scan_user.id,
    )
    issues = json.loads(scan_profile.quality_issues_json)
    assert scan_profile.status == "ready"
    assert scan_profile.fallback_used is True
    assert any(issue["code"] == "PDF_OCR_REQUIRED" for issue in issues)


def test_image_ocr_success_and_unavailable_are_both_persisted(
    db_session,
    tmp_path,
    monkeypatch,
):
    from PIL import Image

    image_path = tmp_path / "job.webp"
    Image.new("RGB", (640, 480), color="white").save(image_path, format="WEBP")
    user, workspace, file_record, _ = add_owned_file(
        db_session,
        image_path,
        file_type="webp",
        mime_type="image/webp",
    )
    monkeypatch.setattr(
        "app.services.file_understanding_service.extract_text_from_image",
        lambda record: {
            "status": "success",
            "engine": "mock",
            "text": "数据分析岗位 Python SQL",
        },
    )
    profile = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    structure = json.loads(profile.structure_json)
    assert structure["width"] == 640
    assert structure["format"] == "WEBP"
    assert structure["ocr_status"] == "success"
    assert "数据分析岗位" in structure["ocr_text_excerpt"]

    def unavailable(_record):
        from app.services.ocr_service import FileOcrError

        raise FileOcrError("OCR 引擎未配置")

    monkeypatch.setattr(
        "app.services.file_understanding_service.extract_text_from_image",
        unavailable,
    )
    degraded = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    degraded_structure = json.loads(degraded.structure_json)
    assert degraded.status == "ready"
    assert degraded.fallback_used is True
    assert degraded_structure["ocr_status"] == "unavailable"


def test_invalid_deepseek_json_degrades_without_overwriting_profile(
    db_session,
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "data.csv"
    path.write_text("id,value\n1,10\n", encoding="utf-8")
    user, workspace, file_record, _ = add_owned_file(
        db_session,
        path,
        file_type="csv",
        mime_type="text/csv",
    )
    monkeypatch.setattr(
        "app.services.file_understanding_service.call_llm",
        lambda **kwargs: SimpleNamespace(
            success=True,
            content="{not valid json",
            message=None,
        ),
    )
    profile = understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        options=FileUnderstandOptions(use_deepseek=True),
    )
    assert profile.status == "ready"
    assert profile.fallback_used is True
    assert profile.suggested_role == "primary_dataset"
    assert get_latest_profile(
        db_session,
        workspace_id=workspace.id,
        file_id=file_record.id,
        owner_user_id=user.id,
    ).id == profile.id


def test_invalid_custom_role_is_rejected(db_session, tmp_path):
    path = tmp_path / "role.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    user, workspace, file_record, _ = add_owned_file(
        db_session,
        path,
        file_type="csv",
        mime_type="text/csv",
    )
    understand_file(
        db_session,
        file_id=file_record.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
    )
    try:
        update_profile_confirmation(
            db_session,
            workspace_id=workspace.id,
            file_id=file_record.id,
            owner_user_id=user.id,
            confirmed_role="custom",
            custom_role="<script>",
            user_tags=None,
        )
    except FileUnderstandingError as exc:
        assert exc.code == "INVALID_CUSTOM_ROLE"
    else:
        raise AssertionError("危险自定义角色应被拒绝")
