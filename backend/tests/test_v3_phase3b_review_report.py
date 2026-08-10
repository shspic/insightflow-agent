"""V3 阶段 3B-1：工程审查报告真实 API、版本快照和导出。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.evidence import Evidence
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_report_asset import ReviewReportAsset
from app.models.review_run import ReviewRun
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.services.review_report_service import canonical_json_bytes, review_state_hash
from app.services.security_service import hash_password


GOLDEN_DIR = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "engineering_review_v1"
    / "golden_case"
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


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):  # noqa: ARG001
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session, tmp_path, monkeypatch):
    session_factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False
    )

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(
        "app.services.review_report_service._storage_root",
        lambda: (tmp_path / "review-reports").resolve(),
    )
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _add_user(db_session, username: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role="user",
        status="active",
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    assert client.get("/api/v2/auth/csrf").status_code == 200
    response = client.post(
        "/api/v2/auth/login",
        headers={settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)},
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}


def _create_workspace(client: TestClient, headers: dict[str, str], name="工程报告") -> int:
    response = client.post(
        "/api/v2/workspaces",
        json={"name": name, "workspace_type": "engineering"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _upload_and_confirm_materials(
    client: TestClient, workspace_id: int, headers: dict[str, str]
) -> None:
    for file_name, role in ROLE_MAP.items():
        path = GOLDEN_DIR / file_name
        mime_type = (
            "application/pdf"
            if path.suffix == ".pdf"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if path.suffix == ".xlsx"
            else "text/markdown"
        )
        upload = client.post(
            f"/api/v2/workspaces/{workspace_id}/files",
            files={"file": (file_name, path.read_bytes(), mime_type)},
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
        file_id = upload.json()["file_id"]
        understand = client.post(
            f"/api/v2/workspaces/{workspace_id}/files/{file_id}/understand",
            json={"use_deepseek": False, "run_ocr": False},
            headers=headers,
        )
        assert understand.status_code in (200, 201), understand.text
        confirm = client.patch(
            f"/api/v2/workspaces/{workspace_id}/files/{file_id}/profile",
            json={"confirmed_role": role},
            headers=headers,
        )
        assert confirm.status_code == 200, confirm.text


def _create_confirmed_brief(
    client: TestClient, workspace_id: int, headers: dict[str, str]
) -> int:
    response = client.post(
        f"/api/v2/workspaces/{workspace_id}/review-briefs",
        json={
            "raw_requirements": "重点检查人员、证书、日期和证据完整性。",
            "interpreted": BRIEF_DATA["interpreted"],
            "interpreter_type": "manual",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    brief_id = response.json()["id"]
    response = client.post(
        f"/api/v2/workspaces/{workspace_id}/review-briefs/{brief_id}/confirm",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return brief_id


def _create_run(
    client: TestClient,
    workspace_id: int,
    brief_id: int,
    headers: dict[str, str],
    *,
    execute: bool = True,
) -> int:
    response = client.post(
        f"/api/v2/workspaces/{workspace_id}/review-runs",
        json={"review_brief_id": brief_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    if execute:
        response = client.post(
            f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/execute",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["finding_count"] == 12
        assert len(response.json()["passed_rule_ids"]) == 2
    return run_id


def _golden_run(client: TestClient, db_session, username: str):
    _add_user(db_session, username)
    headers = _login(client, username)
    workspace_id = _create_workspace(client, headers)
    _upload_and_confirm_materials(client, workspace_id, headers)
    brief_id = _create_confirmed_brief(client, workspace_id, headers)
    run_id = _create_run(client, workspace_id, brief_id, headers)
    return headers, workspace_id, run_id


def _generate_report(
    client: TestClient, workspace_id: int, run_id: int, headers: dict[str, str]
):
    return client.post(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/reports",
        headers=headers,
    )


def _download_assets(client: TestClient, workspace_id: int, run_id: int, report: dict):
    assets = {asset["asset_type"]: asset for asset in report["assets"]}
    downloaded = {}
    for asset_type, asset in assets.items():
        response = client.get(
            f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/reports/"
            f"{report['id']}/assets/{asset['id']}/download"
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            asset["mime_type"].split(";", 1)[0]
        )
        assert asset["file_name"] in response.headers["content-disposition"]
        downloaded[asset_type] = response.content
    return assets, downloaded


def _finding_section(markdown: str, issue_code: str) -> str:
    marker = f" {issue_code} · "
    start = markdown.index(marker)
    next_heading = markdown.find("\n### 7.", start + len(marker))
    end = next_heading if next_heading != -1 else markdown.index("\n## 8.", start)
    return markdown[start:end]


def test_golden_report_assets_evidence_and_idempotency(client, db_session):
    headers, workspace_id, run_id = _golden_run(client, db_session, "report_golden")
    first = _generate_report(client, workspace_id, run_id, headers)
    assert first.status_code == 201, first.text
    report = first.json()
    assert report["reused"] is False
    assert report["version"] == 1
    assert report["finding_count"] == 12
    assert (report["high_count"], report["medium_count"], report["low_count"]) == (6, 6, 0)
    assert report["pending_review_count"] == 12
    assert report["status"] == "ready_with_warnings"
    assert report["warning_count"] >= 3
    assert {asset["asset_type"] for asset in report["assets"]} == {"markdown", "pdf"}

    assets, downloaded = _download_assets(client, workspace_id, run_id, report)
    fetched = client.get(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/reports/{report['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["review_state_hash"] == report["review_state_hash"]
    listed_assets = client.get(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/reports/{report['id']}/assets"
    )
    assert listed_assets.status_code == 200
    assert {item["id"] for item in listed_assets.json()} == {
        item["id"] for item in report["assets"]
    }
    markdown = downloaded["markdown"].decode("utf-8")
    for heading in (
        "## 1. 报告声明",
        "## 2. 项目与审查运行信息",
        "## 3. 审查范围与用户特殊要求",
        "## 4. 材料清单",
        "## 5. 风险概览",
        "## 6. 问题清单",
        "## 7. 逐条问题详情",
        "## 8. 证据索引",
        "## 9. 人工复核记录",
        "## 10. 质量门结果与未决事项",
        "## 11. 可追溯版本信息",
    ):
        assert heading in markdown
    assert "12 条" in markdown and "通过规则：2 条" in markdown
    for file_name in ROLE_MAP:
        assert file_name in markdown
    assert "最终由专业人员确认" in markdown
    assert "合成演示规则" in markdown
    assert "用户自行上传材料" in markdown
    assert "辅助审查" in markdown
    assert "不构成自动合规判断" in markdown
    # 不再包含无条件"所有材料均为合成"的旧声明
    assert "本报告所涉项目、材料、规则和数据均为合成演示内容" not in markdown
    assert "engineering_review_pipeline / v2.1.0" in markdown
    findings = client.get(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/findings"
    ).json()
    for finding in findings:
        detail = _finding_section(markdown, finding["issue_code"])
        assert f"- 规则：{finding['rule_id']} / {finding['rule_version']}" in detail
        assert "- 证据：" in detail
        assert "- 人工复核状态：待复核" in detail

    eq1 = _finding_section(markdown, "SYN-EQ-001")
    eq2 = _finding_section(markdown, "SYN-EQ-002")
    assert "02_合成投标响应.pdf · 第 1 页" in eq1
    assert "03_人员设备清单.xlsx · 项目概况!" in eq1
    assert "02_合成投标响应.pdf · 第 1 页" in eq2
    assert "03_人员设备清单.xlsx · 人员清单!D3" in eq2
    evd1 = _finding_section(markdown, "SYN-EVD-001")
    evd2 = _finding_section(markdown, "SYN-EVD-002")
    assert "03_人员设备清单.xlsx · 人员清单!B3" in evd1
    assert "04_合成资质附件.pdf · 第 2 页" not in evd1
    assert "04_合成资质附件.pdf · 第 2 页" in evd2
    assert "03_人员设备清单.xlsx · 人员清单!B3" not in evd2

    # 阶段 3B-1 补修：姓名与证书 Evidence 不串字段
    all_evidences = client.get(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/evidences"
    ).json()
    # 找到 PDF 端负责人 Evidence
    leader_pdf_evs = [
        e for e in all_evidences
        if e["locator_type"] == "pdf_page" and "项目负责人" in e["quote"]
    ]
    for lev in leader_pdf_evs:
        assert "SYN-JC-24018" not in lev["quote"], (
            f"负责人 Evidence #{lev['id']} 的 quote 不应包含证书编号: {lev['quote']}"
        )
        assert lev["parser_version"] == "v2.1.0", (
            f"新 Evidence #{lev['id']} parser_version 应为 v2.1.0，实际 {lev['parser_version']}"
        )
    # 证书 Evidence 仍正确包含证书编号
    cert_evs = [
        e for e in all_evidences
        if "证书编号" in e["quote"] and "SYN-JC-24018" in e["quote"]
    ]
    assert len(cert_evs) >= 1, "应至少有一条证书 Evidence 包含 SYN-JC-24018"

    # 姓名与证书不串：SYN-EQ-001、SYN-EQ-002 两侧 Evidence 不退化
    findings_by_code = {f["issue_code"]: f for f in findings}
    eq1_evidence_ids = findings_by_code["SYN-EQ-001"]["evidence_ids"]
    eq2_evidence_ids = findings_by_code["SYN-EQ-002"]["evidence_ids"]
    assert len(eq1_evidence_ids) >= 2, f"SYN-EQ-001 应至少有 2 条 Evidence，实际 {len(eq1_evidence_ids)}"
    assert len(eq2_evidence_ids) >= 2, f"SYN-EQ-002 应至少有 2 条 Evidence，实际 {len(eq2_evidence_ids)}"

    for asset_type, content in downloaded.items():
        assert len(content) == assets[asset_type]["size_bytes"]
        assert hashlib.sha256(content).hexdigest() == assets[asset_type]["content_hash"]
    stored_assets = list(
        db_session.scalars(
            select(ReviewReportAsset).where(
                ReviewReportAsset.review_report_id == report["id"]
            )
        ).all()
    )
    assert all(not Path(item.storage_path).is_absolute() for item in stored_assets)
    assert all(".." not in Path(item.storage_path).parts for item in stored_assets)
    stored_report = db_session.get(ReviewReport, report["id"])
    stored_snapshot = json.loads(stored_report.review_snapshot_json)

    # 阶段 3B-1 补修：Evidence 数量口径 — Run 总 Evidence 与报告引用 Evidence 区分
    run_evidence_count = db_session.scalar(
        select(func.count()).select_from(Evidence).where(Evidence.review_run_id == run_id)
    )
    report_evidence_count = len(stored_snapshot["evidences"])
    assert run_evidence_count == 14, f"ReviewRun 总 Evidence 应为 14，实际 {run_evidence_count}"
    assert report_evidence_count == 13, (
        f"ReviewReport 实际引用 Evidence 应为 13，实际 {report_evidence_count}"
    )

    for evidence_snapshot in stored_snapshot["evidences"]:
        evidence = db_session.get(Evidence, evidence_snapshot["id"])
        assert evidence_snapshot["parser_name"] == evidence.parser_name
        assert evidence_snapshot["parser_version"] == evidence.parser_version
    pdf = fitz.open(stream=downloaded["pdf"], filetype="pdf")
    try:
        assert pdf.page_count > 0
        pdf_text = "\n".join(page.get_text() for page in pdf)
    finally:
        pdf.close()
    assert "工程投标资料辅助审查报告" in pdf_text
    assert "报告声明" in pdf_text
    assert "问题清单" in pdf_text
    assert "证据索引" in pdf_text
    assert "可追溯版本信息" in pdf_text
    assert "最终由专业人员确认" in "".join(pdf_text.split())
    # 阶段 3B-1 补修：PDF 新免责声明
    pdf_nospace = "".join(pdf_text.split())
    assert "合成演示规则" in pdf_nospace
    assert "用户自行上传材料" in pdf_nospace
    assert "辅助审查" in pdf_nospace
    assert "不构成自动合规判断" in pdf_nospace
    assert "本报告所涉项目、材料、规则和数据均为合成演示内容" not in pdf_nospace

    workspace = db_session.get(Workspace, workspace_id)
    workspace.description = "与 ReviewRun 审查状态无关的项目信息变化"
    db_session.commit()
    second = _generate_report(client, workspace_id, run_id, headers)
    assert second.status_code == 200
    repeated = second.json()
    assert repeated["reused"] is True
    assert repeated["id"] == report["id"]
    assert repeated["review_state_hash"] == report["review_state_hash"]
    assert [item["id"] for item in repeated["assets"]] == [
        item["id"] for item in report["assets"]
    ]
    assert db_session.scalar(select(func.count()).select_from(Task)) == 0


def test_actions_create_versions_and_history_stays_immutable(client, db_session):
    headers, workspace_id, run_id = _golden_run(client, db_session, "report_versions")
    version1 = _generate_report(client, workspace_id, run_id, headers).json()
    _, version1_assets = _download_assets(client, workspace_id, run_id, version1)
    version1_markdown = version1_assets["markdown"]
    findings = client.get(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/findings"
    ).json()

    confirm = client.post(
        f"/api/v2/workspaces/{workspace_id}/review-findings/{findings[0]['id']}/actions",
        json={"action_type": "confirm", "review_note": "已核对证据"},
        headers=headers,
    )
    assert confirm.status_code == 201
    version2 = _generate_report(client, workspace_id, run_id, headers).json()
    assert version2["version"] == 2
    assert version2["review_state_hash"] != version1["review_state_hash"]
    version2_asset_id = version2["assets"][0]["id"]
    mismatched_asset = client.get(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/reports/"
        f"{version1['id']}/assets/{version2_asset_id}/download"
    )
    assert mismatched_asset.status_code == 404

    modify = client.post(
        f"/api/v2/workspaces/{workspace_id}/review-findings/{findings[1]['id']}/actions",
        json={
            "action_type": "modify",
            "modified_conclusion": "专业人员修改后的结论",
            "modified_suggestion": "专业人员修改后的建议",
            "review_note": "依据复核结果调整",
        },
        headers=headers,
    )
    assert modify.status_code == 201
    version3 = _generate_report(client, workspace_id, run_id, headers).json()
    assert version3["version"] == 3
    _, version3_assets = _download_assets(client, workspace_id, run_id, version3)
    version3_markdown = version3_assets["markdown"].decode("utf-8")
    assert "专业人员修改后的结论" in version3_markdown
    assert "Before" in version3_markdown and "After" in version3_markdown

    for index, finding in enumerate(findings[2:], start=2):
        action_type = "reject" if index == 2 else "resolve" if index == 3 else "confirm"
        response = client.post(
            f"/api/v2/workspaces/{workspace_id}/review-findings/{finding['id']}/actions",
            json={"action_type": action_type, "review_note": f"处理 {index}"},
            headers=headers,
        )
        assert response.status_code == 201
    final_report = _generate_report(client, workspace_id, run_id, headers).json()
    assert final_report["version"] == 4
    assert final_report["pending_review_count"] == 0
    assert final_report["confirmed_count"] == 9
    assert final_report["rejected_count"] == 1
    assert final_report["modified_count"] == 1
    assert final_report["resolved_count"] == 1
    warning_codes = {
        warning["code"] for warning in final_report["quality_gate"]["warnings"]
    }
    assert warning_codes == {"REVIEW_REPORT_OCR_NOT_ENABLED"}
    assert final_report["status"] == "ready_with_warnings"
    _, final_assets = _download_assets(client, workspace_id, run_id, final_report)
    assert "已驳回" in final_assets["markdown"].decode("utf-8")

    listed = client.get(
        f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/reports"
    )
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()] == [4, 3, 2, 1]
    _, version1_again = _download_assets(client, workspace_id, run_id, version1)
    assert version1_again["markdown"] == version1_markdown
    assert b"\xe4\xb8\x93\xe4\xb8\x9a\xe4\xba\xba\xe5\x91\x98\xe4\xbf\xae\xe6\x94\xb9" not in version1_again["markdown"]


def test_quality_gate_blocks_integrity_failures_without_partial_records(client, db_session):
    _add_user(db_session, "report_gate")
    headers = _login(client, "report_gate")
    workspace_id = _create_workspace(client, headers)
    _upload_and_confirm_materials(client, workspace_id, headers)
    brief_id = _create_confirmed_brief(client, workspace_id, headers)
    pending_run_id = _create_run(
        client, workspace_id, brief_id, headers, execute=False
    )
    response = _generate_report(client, workspace_id, pending_run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_RUN_NOT_COMPLETED"

    run_id = _create_run(client, workspace_id, brief_id, headers)
    run = db_session.get(ReviewRun, run_id)
    original_rule_snapshot = run.rule_snapshot_json
    original_rule_hash = run.rule_pack_hash
    run.rule_snapshot_json = "{}"
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR"
    run.rule_pack_hash = hashlib.sha256(b"{}").hexdigest()
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR"
    run.rule_snapshot_json = original_rule_snapshot
    run.rule_pack_hash = original_rule_hash
    db_session.commit()

    original_brief_snapshot = run.review_brief_snapshot_json
    original_brief_hash = run.review_brief_hash
    run.review_brief_snapshot_json = "{}"
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR"
    run.review_brief_hash = hashlib.sha256(b"{}").hexdigest()
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR"
    run.review_brief_snapshot_json = original_brief_snapshot
    run.review_brief_hash = original_brief_hash
    db_session.commit()

    finding = db_session.scalar(
        select(ReviewFinding)
        .where(ReviewFinding.review_run_id == run_id)
        .order_by(ReviewFinding.id)
    )
    original_rule_version = finding.rule_version
    finding.rule_version = ""
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR"
    finding.rule_version = original_rule_version
    db_session.commit()

    original_evidence_ids = finding.evidence_ids_json
    finding.evidence_ids_json = "[]"
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR"
    finding.evidence_ids_json = original_evidence_ids
    db_session.commit()

    finding.evidence_ids_json = "[999999999]"
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR"
    finding.evidence_ids_json = original_evidence_ids
    db_session.commit()

    evidence_id = json.loads(original_evidence_ids)[0]
    evidence = db_session.get(Evidence, evidence_id)
    original_locator = evidence.page_number
    assert evidence.locator_type == "pdf_page"
    evidence.page_number = None
    db_session.commit()
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR"
    evidence.page_number = original_locator
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(ReviewReport)) == 0
    assert db_session.scalar(select(func.count()).select_from(ReviewReportAsset)) == 0


def test_asset_failure_rolls_back_database_and_files(
    client, db_session, monkeypatch, tmp_path
):
    headers, workspace_id, run_id = _golden_run(client, db_session, "report_fail")

    def fail_pdf(*_args, **_kwargs):
        raise RuntimeError("注入 PDF 生成失败")

    monkeypatch.setattr("app.services.review_report_service._write_pdf", fail_pdf)
    response = _generate_report(client, workspace_id, run_id, headers)
    assert response.status_code == 500
    assert response.json()["detail"]["error_code"] == "REVIEW_REPORT_GENERATION_ERROR"
    assert db_session.scalar(select(func.count()).select_from(ReviewReport)) == 0
    assert db_session.scalar(select(func.count()).select_from(ReviewReportAsset)) == 0
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_general_and_multilevel_resource_isolation(client, db_session):
    owner = _add_user(db_session, "report_owner")
    _add_user(db_session, "report_other")
    headers = _login(client, owner.username)
    workspace_id = _create_workspace(client, headers, "A")
    other_workspace_id = _create_workspace(client, headers, "B")
    _upload_and_confirm_materials(client, workspace_id, headers)
    brief_id = _create_confirmed_brief(client, workspace_id, headers)
    run_id = _create_run(client, workspace_id, brief_id, headers)
    report = _generate_report(client, workspace_id, run_id, headers).json()
    asset_id = report["assets"][0]["id"]

    general = client.post(
        "/api/v2/workspaces",
        json={"name": "通用", "workspace_type": "general"},
        headers=headers,
    ).json()["id"]
    assert _generate_report(client, general, run_id, headers).status_code == 403

    wrong_base = (
        f"/api/v2/workspaces/{other_workspace_id}/review-runs/{run_id}/reports/{report['id']}"
    )
    assert client.get(wrong_base).status_code == 404
    assert client.get(f"{wrong_base}/assets").status_code == 404
    assert client.get(f"{wrong_base}/assets/{asset_id}/download").status_code == 404

    client.cookies.clear()
    other_headers = _login(client, "report_other")
    base = f"/api/v2/workspaces/{workspace_id}/review-runs/{run_id}/reports"
    assert client.get(base, headers=other_headers).status_code == 404
    assert client.get(f"{base}/{report['id']}", headers=other_headers).status_code == 404
    assert client.get(f"{base}/{report['id']}/assets", headers=other_headers).status_code == 404
    assert client.get(
        f"{base}/{report['id']}/assets/{asset_id}/download", headers=other_headers
    ).status_code == 404


def test_canonical_hash_is_stable_and_report_code_has_no_fixture_answer_dependency():
    left = {"中文": [3, 2, 1], "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "中文": [3, 2, 1]}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert review_state_hash(left) == review_state_hash(right)
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "review_report_service.py"
    ).read_text(encoding="utf-8")
    assert "SYN-JC-24018" not in source
    assert "SYN-EQ-001" not in source
    assert "SYN-EQ-002" not in source
    assert "ground_truth" not in source
