import json

import fitz
from docx import Document
from sqlalchemy import select

from app.models.file import File
from app.models.file_chunk import FileChunk
from app.models.report_asset import ReportAsset
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services import file_understanding_service as understanding
from app.services import report_version_service as reports
from app.services.ocr_service import FileOcrError
from app.services.report_template_service import list_report_templates


def _scope(db_session):
    user = User(username="report-owner", password_hash="x", role="user", status="active")
    other = User(username="report-other", password_hash="x", role="user", status="active")
    db_session.add_all([user, other])
    db_session.flush()
    workspace = Workspace(owner_user_id=user.id, name="报告测试")
    db_session.add(workspace)
    db_session.flush()
    task = Task(
        owner_user_id=user.id,
        workspace_id=workspace.id,
        user_input="分析资料",
        status="completed",
        file_ids_json="[]",
        agent_state_json="{}",
    )
    db_session.add(task)
    db_session.flush()
    return user, other, workspace, task


def _state():
    return {
        "clarified_request": "分析销售趋势并给出建议",
        "workspace_context": {
            "files": [{"filename": "sales.csv", "effective_role": "primary_dataset"}],
            "data_quality_issues": [],
        },
        "analysis_findings": [
            {"metric": "收入", "value": 120, "calculation_method": "sum(revenue)"}
        ],
        "document_evidence": [
            {"filename": "rules.pdf", "page_number": 2, "snippet": "收入按含税金额统计"}
        ],
        "warnings": ["样本规模较小"],
        "assumptions": ["币种为人民币"],
    }


def test_report_versions_templates_and_exports(db_session, tmp_path, monkeypatch):
    user, other, workspace, task = _scope(db_session)
    monkeypatch.setattr(reports, "_storage_root", lambda: tmp_path)

    first = reports.create_report_version(
        db_session,
        task=task,
        state=_state(),
        template_key="comprehensive_analysis",
        generation_source="initial",
    )
    second = reports.create_report_version(
        db_session,
        task=task,
        state=_state(),
        template_key="student_research",
        generation_source="user_regenerate",
        correction_note="补充课程讨论。",
    )
    db_session.commit()

    assert first.version == 1
    assert second.version == 2
    assert task.report_id == second.id
    assert first.markdown_content != second.markdown_content
    assert len(list_report_templates()) == 3
    assert reports.list_owned_reports(
        db_session,
        workspace_id=workspace.id,
        task_id=task.id,
        owner_user_id=other.id,
    ) == []
    reports.set_current_report(db_session, task=task, report=first)
    assert task.report_id == first.id
    reports.set_current_report(db_session, task=task, report=second)
    assert task.report_id == second.id

    markdown = reports.export_report(db_session, report=second, export_format="markdown")
    docx = reports.export_report(db_session, report=second, export_format="docx")
    pdf = reports.export_report(db_session, report=second, export_format="pdf")
    repeated = reports.export_report(db_session, report=second, export_format="pdf")
    db_session.commit()

    assert repeated.id == pdf.id
    assert reports.resolve_asset_path(markdown).read_text(encoding="utf-8") == second.markdown_content
    document = Document(reports.resolve_asset_path(docx))
    assert "学生调研报告" in "\n".join(item.text for item in document.paragraphs)
    pdf_document = fitz.open(reports.resolve_asset_path(pdf))
    assert len(pdf_document) >= 1
    assert "学生调研报告" in "".join(page.get_text() for page in pdf_document)
    pdf_document.close()
    assert not any(str(item.storage_key).startswith(("/", "\\")) for item in [markdown, docx, pdf])


def test_report_delete_protects_current_and_only_version(db_session, tmp_path, monkeypatch):
    _, _, _, task = _scope(db_session)
    monkeypatch.setattr(reports, "_storage_root", lambda: tmp_path)
    first = reports.create_report_version(db_session, task=task, state=_state())
    db_session.flush()
    try:
        reports.delete_report_version(db_session, task=task, report=first)
    except reports.ReportVersionError as exc:
        assert exc.code == "REPORT_DELETE_BLOCKED"
    else:
        raise AssertionError("唯一报告不得删除")


def test_scanned_pdf_ocr_is_page_scoped_and_idempotent(db_session, tmp_path, monkeypatch):
    user, _, workspace, _ = _scope(db_session)
    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()
    record = File(
        owner_user_id=user.id,
        filename="scan.pdf",
        file_type="pdf",
        file_path=str(pdf_path),
        status="uploaded",
    )
    db_session.add(record)
    db_session.flush()
    db_session.add(WorkspaceFile(workspace_id=workspace.id, file_id=record.id))
    db_session.flush()

    monkeypatch.setattr(
        understanding,
        "extract_scanned_pdf_pages",
        lambda path, pages: [
            {
                "page_number": 1,
                "status": "success",
                "text": "这是扫描页面识别出的合成测试文本。",
                "confidence": 0.91,
                "source_type": "scanned_pdf_ocr",
            }
        ],
    )
    parsed = understanding._parse_pdf(db_session, record, pdf_path, run_ocr=True)
    parsed_again = understanding._parse_pdf(db_session, record, pdf_path, run_ocr=True)
    chunks = db_session.scalars(
        select(FileChunk).where(
            FileChunk.file_id == record.id,
            FileChunk.source_type == "scanned_pdf_ocr",
        )
    ).all()
    assert parsed["structure"]["ocr"]["successful_pages"] == [1]
    assert parsed_again["structure"]["ocr"]["successful_pages"] == [1]
    assert len(chunks) == 1
    assert chunks[0].page_number == 1


def test_text_pdf_skips_ocr_and_unavailable_ocr_degrades(db_session, tmp_path, monkeypatch):
    user, _, workspace, _ = _scope(db_session)
    text_pdf = tmp_path / "text.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "This page already contains enough extractable text for indexing.")
    document.save(text_pdf)
    document.close()
    record = File(
        owner_user_id=user.id,
        filename="text.pdf",
        file_type="pdf",
        file_path=str(text_pdf),
        status="uploaded",
    )
    db_session.add(record)
    db_session.flush()
    db_session.add(WorkspaceFile(workspace_id=workspace.id, file_id=record.id))
    db_session.flush()

    def forbidden(*args, **kwargs):
        raise AssertionError("文本页不应执行 OCR")

    monkeypatch.setattr(understanding, "extract_scanned_pdf_pages", forbidden)
    parsed = understanding._parse_pdf(db_session, record, text_pdf, run_ocr=True)
    assert parsed["structure"]["ocr"]["candidate_pages"] == []

    empty_pdf = tmp_path / "empty.pdf"
    document = fitz.open()
    document.new_page()
    document.save(empty_pdf)
    document.close()
    record.file_path = str(empty_pdf)
    monkeypatch.setattr(
        understanding,
        "extract_scanned_pdf_pages",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileOcrError("Tesseract 不可用")),
    )
    degraded = understanding._parse_pdf(db_session, record, empty_pdf, run_ocr=True)
    codes = {item["code"] for item in degraded["quality_issues"]}
    assert "PDF_OCR_UNAVAILABLE" in codes
