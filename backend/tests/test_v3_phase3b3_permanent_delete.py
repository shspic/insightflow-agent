"""V3 阶段 3B-3：永久删除与归档语义收敛 — 验收阻断补修测试。

覆盖：
- 路径解析（相对/绝对/穿越/根目录外）— 全部使用 tmp_path
- 名称严格匹配
- deleted_counts 语义（含 review_report_assets）
- 两阶段事务安全（真实 DELETE API + commit 失败注入）
- 非法路径安全 warning（不静默跳过）
- 真实 OSError 不泄露路径（只读文件触发 PermissionError）
- 真实磁盘资产创建与删除断言（ReportAsset, ReviewReport Markdown/PDF）
- 缺失文件幂等
- 配额回收
- app.db 全 session 隔离（autouse）
- 共享文件保留
"""

from __future__ import annotations

import hashlib
import json
import stat as stat_module
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.timeutils import utcnow
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.evidence import Evidence
from app.models.file import File
from app.models.file_profile import FileProfile
from app.models.file_relation import FileRelation
from app.models.file_processing_run import FileProcessingRun
from app.models.report import Report as ReportModel
from app.models.report_asset import ReportAsset
from app.models.review_action import ReviewAction
from app.models.review_brief import ReviewBrief
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_report_asset import ReviewReportAsset
from app.models.review_run import ReviewRun
from app.models.task import Task
from app.models.usage import UsageCounter
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_file import WorkspaceFile
from app.services.security_service import hash_password

PASSWORD = "SafePassword!2026"
APP_DB = Path(__file__).resolve().parents[1] / "data" / "app.db"


# ═══════════════════════════════════════════════════════════════════════
# session 级 app.db 隔离 — autouse，全程验证
# ═══════════════════════════════════════════════════════════════════════

_original_app_db_hash: str | None = None


@pytest.fixture(scope="session", autouse=True)
def _protect_app_db():
    """session 开始时记录 app.db SHA256，全部测试结束后验证未被修改。"""
    global _original_app_db_hash
    if APP_DB.is_file():
        _original_app_db_hash = hashlib.sha256(APP_DB.read_bytes()).hexdigest()
    yield
    if _original_app_db_hash is not None and APP_DB.is_file():
        current = hashlib.sha256(APP_DB.read_bytes()).hexdigest()
        assert current == _original_app_db_hash, (
            f"app.db 已被修改：{_original_app_db_hash[:16]} → {current[:16]}"
        )


# ═══════════════════════════════════════════════════════════════════════
# 隔离数据库 + 隔离存储
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = sf()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session, tmp_path, monkeypatch):
    sf = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)

    def override_db():
        db = sf()
        try:
            yield db
        finally:
            db.close()

    upload_dir = tmp_path / "uploads"
    report_dir = tmp_path / "reports"
    upload_dir.mkdir()
    report_dir.mkdir()

    monkeypatch.setattr(
        "app.services.file_service._resolve_upload_dir",
        lambda: upload_dir,
    )

    def _patched_resolve_report(storage_path):
        from app.services.workspace_service import _resolve_and_validate_path
        return _resolve_and_validate_path(storage_path, report_dir)

    monkeypatch.setattr(
        "app.services.workspace_service._resolve_report_path",
        _patched_resolve_report,
    )

    monkeypatch.setattr(
        "app.services.review_report_service._storage_root",
        lambda: report_dir.resolve(),
    )

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════

def _add_user(db_session, username="testuser"):
    u = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role="user",
        status="active",
        must_change_password=False,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _session_csrf(client):
    from app.core.config import settings as s
    return {s.csrf_header_name: client.cookies.get(s.csrf_cookie_name)}


def _login(client, username="testuser"):
    assert client.get("/api/v2/auth/csrf").status_code == 200
    r = client.post(
        "/api/v2/auth/login",
        headers=_session_csrf(client),
        json={"username": username, "password": PASSWORD},
    )
    assert r.status_code == 200
    return _session_csrf(client)


def _create_ws(client, h, name="测试", wtype="engineering"):
    r = client.post(
        "/api/v2/workspaces",
        json={"name": name, "workspace_type": wtype},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _del(client, ws_id, name, h):
    headers = {**h, "Content-Type": "application/json"}
    return client.request(
        "DELETE",
        f"/api/v2/workspaces/{ws_id}",
        content=json.dumps({"confirmation_name": name}),
        headers=headers,
    )


def _upload_file(client, ws_id, h, filename="sample.csv", content=b"name,score\nAlice,95\n"):
    r = client.post(
        f"/api/v2/workspaces/{ws_id}/files",
        files={"file": (filename, content, "text/csv")},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════════
# 1. 路径解析 — 全部使用 tmp_path
# ═══════════════════════════════════════════════════════════════════════

class TestPathResolution:
    """验证 _resolve_and_validate_path 对各类路径的行为。"""

    def test_relative_path_within_root(self, tmp_path):
        from app.services.workspace_service import _resolve_and_validate_path
        root = tmp_path / "root"
        root.mkdir()
        result = _resolve_and_validate_path("subdir/file.txt", root)
        assert result is not None
        assert result == (root / "subdir/file.txt").resolve()

    def test_absolute_path_within_root(self, tmp_path):
        """核心修复：根目录内的绝对路径应被接受。"""
        from app.services.workspace_service import _resolve_and_validate_path
        root = tmp_path / "root"
        sub = root / "subdir"
        sub.mkdir(parents=True)
        abs_inside = (sub / "file.txt").resolve()
        abs_inside.write_text("hello")
        result = _resolve_and_validate_path(str(abs_inside), root.resolve())
        assert result is not None
        assert result == abs_inside

    def test_absolute_path_outside_root(self, tmp_path):
        from app.services.workspace_service import _resolve_and_validate_path
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside" / "file.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("secret")
        result = _resolve_and_validate_path(str(outside.resolve()), root.resolve())
        assert result is None

    def test_dotdot_traversal_rejected(self, tmp_path):
        from app.services.workspace_service import _resolve_and_validate_path
        root = tmp_path / "root"
        root.mkdir()
        result = _resolve_and_validate_path("../outside/file.txt", root)
        assert result is None

    def test_dotdot_in_middle_rejected(self, tmp_path):
        from app.services.workspace_service import _resolve_and_validate_path
        root = tmp_path / "root"
        root.mkdir()
        result = _resolve_and_validate_path("subdir/../../outside/file.txt", root)
        assert result is None

    def test_non_existent_relative_path_still_resolves(self, tmp_path):
        from app.services.workspace_service import _resolve_and_validate_path
        root = tmp_path / "root"
        root.mkdir()
        result = _resolve_and_validate_path("nonexistent/file.txt", root)
        assert result is not None

    def test_root_dir_itself_rejected(self, tmp_path):
        """存储根目录本身必须被拒绝，不得加入 cleanup_plan。"""
        from app.services.workspace_service import _resolve_and_validate_path
        root = tmp_path / "root"
        root.mkdir()
        # "." 解析后等于 root，应被拒绝
        result = _resolve_and_validate_path(".", root)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# 2. 名称确认严格性
# ═══════════════════════════════════════════════════════════════════════

class TestNameConfirmation:
    def test_exact_match_succeeds(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "测试项目")
        r = _del(client, ws_id, "测试项目", h)
        assert r.status_code == 200

    def test_leading_space_rejected(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "测试项目")
        r = _del(client, ws_id, " 测试项目", h)
        assert r.status_code == 400
        assert r.json()["detail"]["error_code"] == "WORKSPACE_DELETE_CONFIRMATION_MISMATCH"

    def test_trailing_space_rejected(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "测试项目")
        r = _del(client, ws_id, "测试项目 ", h)
        assert r.status_code == 400
        assert db_session.get(Workspace, ws_id) is not None

    def test_case_mismatch_rejected(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "TestProject")
        r = _del(client, ws_id, "testproject", h)
        assert r.status_code == 400

    def test_empty_string_rejected(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "测试项目")
        r = _del(client, ws_id, "", h)
        assert r.status_code == 400

    def test_name_with_internal_spaces_exact(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "A  B")  # 双空格
        r = _del(client, ws_id, "A B", h)  # 单空格
        assert r.status_code == 400
        r2 = _del(client, ws_id, "A  B", h)  # 双空格 exact
        assert r2.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# 3. 基础删除契约
# ═══════════════════════════════════════════════════════════════════════

class TestDeleteContract:
    def test_empty_engineering_delete(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "空工程", wtype="engineering")
        r = _del(client, ws_id, "空工程", h)
        assert r.status_code == 200
        data = r.json()
        assert data["message"] == "项目已永久删除"
        assert data["workspace_id"] == ws_id
        dc = data["deleted_counts"]
        assert dc["workspace_files"] == 0
        assert dc["tasks"] == 0
        assert dc["files_deleted"] == 0
        assert dc["files_preserved_shared"] == 0
        assert "review_report_assets" in dc
        assert db_session.get(Workspace, ws_id) is None

    def test_empty_general_delete(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "空通用", wtype="general")
        r = _del(client, ws_id, "空通用", h)
        assert r.status_code == 200
        assert db_session.get(Workspace, ws_id) is None

    def test_deleted_returns_404(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "待删")
        assert _del(client, ws_id, "待删", h).status_code == 200
        assert client.get(f"/api/v2/workspaces/{ws_id}", headers=h).status_code == 404

    def test_restore_returns_410(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "不可恢复")
        _del(client, ws_id, "不可恢复", h)
        assert client.post(
            f"/api/v2/workspaces/{ws_id}/restore", headers=h
        ).status_code == 410

    def test_cross_user_returns_404(self, client, db_session):
        _add_user(db_session, "owner")
        _add_user(db_session, "other")
        h1 = _login(client, "owner")
        ws_id = _create_ws(client, h1, "所有者项目")
        client.cookies.clear()
        h2 = _login(client, "other")
        assert _del(client, ws_id, "所有者项目", h2).status_code == 404

    def test_archive_and_restore_active_still_works(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "归档测试")
        r = client.patch(
            f"/api/v2/workspaces/{ws_id}",
            json={"status": "archived"},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "archived"
        r2 = client.patch(
            f"/api/v2/workspaces/{ws_id}",
            json={"status": "active"},
            headers=h,
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "active"


# ═══════════════════════════════════════════════════════════════════════
# 4. 真实磁盘资产
# ═══════════════════════════════════════════════════════════════════════

class TestDiskAssets:
    def test_uploaded_file_deleted_from_disk(self, client, db_session):
        """上传文件在永久删除后从磁盘消失。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "磁盘测试")

        uploaded = _upload_file(client, ws_id, h, "data.csv", b"a,b\n1,2\n")
        fid = uploaded["file_id"]

        file_record = db_session.get(File, fid)
        phys = Path(file_record.file_path)
        assert phys.is_file(), f"上传文件应存在于 {phys}"

        r = _del(client, ws_id, "磁盘测试", h)
        assert r.status_code == 200
        assert not phys.exists(), f"上传文件 {phys} 删除后应不存在"
        db_session.expire_all()
        assert db_session.get(File, fid) is None

    def test_task_report_file_deleted(self, client, db_session, tmp_path):
        """Task 关联的 report 文件被删除。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "报告删除")

        user = db_session.scalar(select(User).where(User.username == "testuser"))

        task = Task(
            workspace_id=ws_id,
            owner_user_id=user.id,
            user_input="测试任务",
            status="success",
            file_ids_json="[]",
        )
        db_session.add(task)
        db_session.commit()

        report_file = tmp_path / "reports" / "test-report.md"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text("# Test Report", encoding="utf-8")
        task.report_path = str(report_file.relative_to(tmp_path / "reports"))
        db_session.commit()

        assert report_file.is_file()

        r = _del(client, ws_id, "报告删除", h)
        assert r.status_code == 200
        assert not report_file.exists(), "Task 报告文件应被删除"

    def test_general_report_asset_deleted_from_disk(self, client, db_session, tmp_path):
        """通用 ReportAsset 文件在永久删除后从磁盘消失。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "通用资产删除")
        user = db_session.scalar(select(User).where(User.username == "testuser"))

        # 创建 Task → Report → ReportAsset 链
        task = Task(
            workspace_id=ws_id,
            owner_user_id=user.id,
            user_input="资产测试任务",
            status="success",
            file_ids_json="[]",
        )
        db_session.add(task)
        db_session.commit()

        report = ReportModel(
            workspace_id=ws_id,
            task_id=task.id,
            owner_user_id=user.id,
            title="测试报告",
            template_key="general_v1",
            generation_source="initial",
            markdown_content="# Test",
            status="ready",
            version=1,
        )
        db_session.add(report)
        db_session.commit()

        # 真实创建报告资产文件
        report_dir = tmp_path / "reports"
        asset_file = report_dir / "chart-1.png"
        asset_file.write_text("fake png content")

        asset = ReportAsset(
            report_id=report.id,
            task_id=task.id,
            workspace_id=ws_id,
            owner_user_id=user.id,
            asset_type="chart",
            format="png",
            display_name="图表1",
            storage_key=str(asset_file.relative_to(report_dir)),
            mime_type="image/png",
            size_bytes=len("fake png content"),
            status="ready",
        )
        db_session.add(asset)
        db_session.commit()

        asset_id = asset.id
        assert asset_file.is_file()
        assert db_session.get(ReportAsset, asset_id) is not None

        r = _del(client, ws_id, "通用资产删除", h)
        assert r.status_code == 200
        assert not asset_file.exists(), "通用报告资产文件应被删除"
        db_session.expire_all()
        assert db_session.get(ReportAsset, asset_id) is None

    def test_review_report_assets_deleted_from_disk(self, client, db_session, tmp_path):
        """工程 ReviewReport Markdown 和 PDF 资产真实从磁盘删除。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "工程资产删除")
        user = db_session.scalar(select(User).where(User.username == "testuser"))

        # 创建 ReviewBrief → ReviewRun → ReviewReport → ReviewReportAsset 链
        brief = ReviewBrief(
            workspace_id=ws_id,
            owner_user_id=user.id,
            version=1,
            raw_requirements="# Spec",
            interpreted_json="{}",
            content_hash="abc123",
            status="confirmed",
        )
        db_session.add(brief)
        db_session.commit()

        run = ReviewRun(
            workspace_id=ws_id,
            owner_user_id=user.id,
            review_template_key="engineering_bid_review_v1",
            rule_pack_id="default",
            rule_pack_version="1.0",
            rule_pack_hash="abc",
            rule_snapshot_json="{}",
            review_brief_id=brief.id,
            status="completed",
        )
        db_session.add(run)
        db_session.commit()

        report = ReviewReport(
            workspace_id=ws_id,
            owner_user_id=user.id,
            review_run_id=run.id,
            version=1,
            status="ready",
            review_state_hash="abc123",
            review_snapshot_json="{}",
            quality_gate_json="{}",
            generator_name="test_generator",
            generator_version="1.0",
        )
        db_session.add(report)
        db_session.commit()

        # 创建真实 Markdown 和 PDF 资产文件
        report_dir = tmp_path / "reports"
        md_file = report_dir / "review-report-v1.md"
        pdf_file = report_dir / "review-report-v1.pdf"
        md_file.write_text("# Review Report Content", encoding="utf-8")
        pdf_file.write_text("%PDF-1.4 fake pdf")

        md_asset = ReviewReportAsset(
            review_report_id=report.id,
            workspace_id=ws_id,
            owner_user_id=user.id,
            asset_type="markdown",
            file_name="review-report-v1.md",
            storage_path=str(md_file.relative_to(report_dir)),
            mime_type="text/markdown",
            size_bytes=len("# Review Report Content"),
            content_hash="sha256:fake",
        )
        db_session.add(md_asset)

        pdf_asset = ReviewReportAsset(
            review_report_id=report.id,
            workspace_id=ws_id,
            owner_user_id=user.id,
            asset_type="pdf",
            file_name="review-report-v1.pdf",
            storage_path=str(pdf_file.relative_to(report_dir)),
            mime_type="application/pdf",
            size_bytes=len("%PDF-1.4 fake pdf"),
            content_hash="sha256:fake2",
        )
        db_session.add(pdf_asset)
        db_session.commit()

        md_asset_id = md_asset.id
        pdf_asset_id = pdf_asset.id
        assert md_file.is_file()
        assert pdf_file.is_file()
        assert db_session.get(ReviewReportAsset, md_asset_id) is not None
        assert db_session.get(ReviewReportAsset, pdf_asset_id) is not None

        r = _del(client, ws_id, "工程资产删除", h)
        assert r.status_code == 200

        assert not md_file.exists(), "Markdown 资产文件应被删除"
        assert not pdf_file.exists(), "PDF 资产文件应被删除"
        db_session.expire_all()
        assert db_session.get(ReviewReportAsset, md_asset_id) is None
        assert db_session.get(ReviewReportAsset, pdf_asset_id) is None

    def test_deleted_counts_includes_all_keys(self, client, db_session):
        """验证 deleted_counts 包含所有必要 key，含 review_report_assets。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "计数测试")

        _upload_file(client, ws_id, h, "f1.csv", b"a,b\n1,2\n")
        _upload_file(client, ws_id, h, "f2.csv", b"x,y\n3,4\n")

        r = _del(client, ws_id, "计数测试", h)
        assert r.status_code == 200
        dc = r.json()["deleted_counts"]
        assert dc["workspace_files"] == 2
        assert dc["files_deleted"] == 2
        assert dc["files_preserved_shared"] == 0
        assert dc["tasks"] == 0

        required_keys = [
            "workspace_files", "files_deleted", "files_preserved_shared",
            "tasks", "reports", "report_assets", "review_briefs",
            "review_runs", "review_findings", "review_reports",
            "review_report_assets", "review_actions", "evidences",
            "file_profiles", "file_processing_runs", "file_relations",
        ]
        for key in required_keys:
            assert key in dc, f"缺少 key: {key}"
            assert isinstance(dc[key], int), f"{key} 应为 int"

    def test_review_report_assets_count_correct(self, client, db_session, tmp_path):
        """精确验证 deleted_counts['review_report_assets'] 值。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "资产计数")
        user = db_session.scalar(select(User).where(User.username == "testuser"))

        brief = ReviewBrief(
            workspace_id=ws_id, owner_user_id=user.id,
            version=1, raw_requirements="# Spec",
            interpreted_json="{}", content_hash="abc123",
            status="confirmed",
        )
        db_session.add(brief)
        db_session.commit()

        run = ReviewRun(
            workspace_id=ws_id, owner_user_id=user.id,
            review_template_key="engineering_bid_review_v1",
            rule_pack_id="default", rule_pack_version="1.0",
            rule_pack_hash="abc", rule_snapshot_json="{}",
            review_brief_id=brief.id, status="completed",
        )
        db_session.add(run)
        db_session.commit()

        report = ReviewReport(
            workspace_id=ws_id, owner_user_id=user.id,
            review_run_id=run.id, version=1, status="ready",
            review_state_hash="def456",
            review_snapshot_json="{}",
            quality_gate_json="{}",
            generator_name="test_generator",
            generator_version="1.0",
        )
        db_session.add(report)
        db_session.commit()

        report_dir = tmp_path / "reports"
        for asset_type, fname in [("markdown", "rpt.md"), ("pdf", "rpt.pdf")]:
            fpath = report_dir / fname
            fpath.write_text("content")
            db_session.add(ReviewReportAsset(
                review_report_id=report.id, workspace_id=ws_id,
                owner_user_id=user.id, asset_type=asset_type,
                file_name=fname,
                storage_path=str(fpath.relative_to(report_dir)),
                mime_type="text/markdown" if asset_type == "markdown" else "application/pdf",
                size_bytes=7, content_hash=f"hash:{asset_type}",
            ))
        db_session.commit()

        r = _del(client, ws_id, "资产计数", h)
        assert r.status_code == 200
        dc = r.json()["deleted_counts"]
        assert dc["review_reports"] == 1
        assert dc["review_report_assets"] == 2

    def test_shared_file_preserved_on_disk(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws1 = _create_ws(client, h, "共享源")
        ws2 = _create_ws(client, h, "共享目标")

        uploaded = _upload_file(client, ws1, h, "shared.csv", b"x,y\n1,2\n")
        fid = uploaded["file_id"]

        wf2 = WorkspaceFile(workspace_id=ws2, file_id=fid)
        db_session.add(wf2)
        db_session.commit()

        file_record = db_session.get(File, fid)
        phys = Path(file_record.file_path)
        assert phys.is_file()

        r = _del(client, ws1, "共享源", h)
        assert r.status_code == 200
        assert r.json()["deleted_counts"]["files_preserved_shared"] == 1
        assert r.json()["deleted_counts"]["files_deleted"] == 0
        assert db_session.get(File, fid) is not None
        assert phys.is_file(), "共享文件物理文件应保留"

    def test_orphan_file_deleted_from_db_and_disk(self, client, db_session):
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "孤儿文件")

        uploaded = _upload_file(client, ws_id, h, "orphan.csv", b"k,v\na,b\n")
        fid = uploaded["file_id"]
        file_record = db_session.get(File, fid)
        assert file_record is not None

        phys = Path(file_record.file_path)
        assert phys.is_file()

        r = _del(client, ws_id, "孤儿文件", h)
        assert r.status_code == 200
        assert r.json()["deleted_counts"]["files_deleted"] == 1
        assert r.json()["deleted_counts"]["files_preserved_shared"] == 0
        db_session.expire_all()
        assert db_session.get(File, fid) is None
        assert not phys.exists(), "孤儿文件物理文件应删除"

    def test_outside_root_file_preserved_with_warning(self, client, db_session, tmp_path):
        """根目录外文件保留，API 返回安全 warning。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "外部路径")
        user = db_session.scalar(select(User).where(User.username == "testuser"))

        # 在 uploads/reports 目录之外创建文件
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("should not be deleted")

        task = Task(
            workspace_id=ws_id,
            owner_user_id=user.id,
            user_input="外部路径任务",
            status="success",
            file_ids_json="[]",
            report_path=str(outside_file),  # 绝对路径，不在 report_dir 内
        )
        db_session.add(task)
        db_session.commit()

        r = _del(client, ws_id, "外部路径", h)
        assert r.status_code == 200
        assert outside_file.is_file(), "根目录外的文件应保留"

        # 应有安全 warning
        warnings = r.json()["storage_cleanup_warnings"]
        task_report_warnings = [w for w in warnings if "task_report:" in w]
        assert len(task_report_warnings) >= 1, "非法路径应产生 warning"
        for w in task_report_warnings:
            assert "路径不安全" in w
            assert "outside" not in w, f"warning 不应含路径: {w}"

    def test_root_dir_rejected_with_skipped_warning(self, client, db_session, tmp_path):
        """存储根目录本身被拒绝，产生安全 warning。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "根目录测试")
        user = db_session.scalar(select(User).where(User.username == "testuser"))

        # report_path="." 解析后等于 report_dir 根目录，被 _resolve_and_validate_path 拒绝
        task = Task(
            workspace_id=ws_id,
            owner_user_id=user.id,
            user_input="根目录任务",
            status="success",
            file_ids_json="[]",
            report_path=".",
        )
        db_session.add(task)
        db_session.commit()

        r = _del(client, ws_id, "根目录测试", h)
        assert r.status_code == 200
        warnings = r.json()["storage_cleanup_warnings"]
        task_warnings = [w for w in warnings if "task_report:" in w]
        assert len(task_warnings) >= 1, "根目录路径应产生 skipped_cleanup warning"
        for w in task_warnings:
            assert "路径不安全" in w

    def test_directory_not_deleted_with_warning(self, client, db_session, tmp_path):
        """目录（非普通文件）不会被删除，产生安全 warning。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "目录删除测试")
        user = db_session.scalar(select(User).where(User.username == "testuser"))

        # 在 report_dir 内创建子目录，并非普通文件
        report_dir = tmp_path / "reports"
        sub_dir = report_dir / "subdir"
        sub_dir.mkdir()

        task = Task(
            workspace_id=ws_id,
            owner_user_id=user.id,
            user_input="目录任务",
            status="success",
            file_ids_json="[]",
            report_path="subdir",  # 解析后是目录，不是普通文件
        )
        db_session.add(task)
        db_session.commit()

        assert sub_dir.is_dir()

        r = _del(client, ws_id, "目录删除测试", h)
        assert r.status_code == 200
        assert sub_dir.is_dir(), "目录不应被删除"

        warnings = r.json()["storage_cleanup_warnings"]
        task_warnings = [w for w in warnings if "task_report:" in w]
        assert len(task_warnings) >= 1, "非普通文件应产生 warning"
        for w in task_warnings:
            assert "磁盘文件清理失败" in w
            assert "subdir" not in w, f"warning 不应含路径: {w}"

    def test_missing_file_is_idempotent(self, client, db_session, tmp_path):
        """文件已不存在时，删除成功且不产生 warning。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "缺失文件")

        _upload_file(client, ws_id, h, "will-vanish.csv", b"a,b\n1,2\n")

        # 手动删除物理文件但不更新 DB
        from app.services.file_service import _resolve_upload_dir
        upload_dir = _resolve_upload_dir()
        all_files = list(upload_dir.iterdir())
        assert len(all_files) > 0
        for f in all_files:
            if f.suffix == ".csv":
                f.unlink()
                break

        r = _del(client, ws_id, "缺失文件", h)
        assert r.status_code == 200
        assert r.json()["storage_cleanup_warnings"] == []

    def test_oserror_fixed_message_no_path_leak(self, client, db_session, tmp_path, monkeypatch):
        """真实 PermissionError（含空格路径）不泄露路径，使用固定安全信息。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "权限泄露测试")
        user = db_session.scalar(select(User).where(User.username == "testuser"))

        # 创建含空格的敏感路径
        secret_dir = tmp_path / "Test User" / "Secret Project"
        secret_dir.mkdir(parents=True)
        locked_file = secret_dir / "private file.pdf"
        locked_file.write_text("classified content")

        # 让 _resolve_report_path 以 tmp_path 为根，使得 locked_file 的相对路径可解析
        def _patched_resolve_report(storage_path):
            from app.services.workspace_service import _resolve_and_validate_path
            return _resolve_and_validate_path(storage_path, tmp_path)

        monkeypatch.setattr(
            "app.services.workspace_service._resolve_report_path",
            _patched_resolve_report,
        )

        # 创建 Task，report_path 指向带空格的文件
        rel_path = str(locked_file.relative_to(tmp_path))
        task = Task(
            workspace_id=ws_id,
            owner_user_id=user.id,
            user_input="权限测试",
            status="success",
            file_ids_json="[]",
            report_path=rel_path,
        )
        db_session.add(task)
        db_session.commit()

        # 设为只读以触发真实 PermissionError
        locked_file.chmod(stat_module.S_IREAD)

        try:
            r = _del(client, ws_id, "权限泄露测试", h)
            assert r.status_code == 200
            warnings = r.json()["storage_cleanup_warnings"]
            assert len(warnings) >= 1, f"应有至少 1 条 warning，实际: {warnings}"

            for w in warnings:
                # 不得泄露任何路径信息
                assert "C:" not in w, f"warning 不应含盘符: {w}"
                assert "Users" not in w, f"warning 不应含用户目录: {w}"
                assert "Test User" not in w, f"warning 不应含目录名: {w}"
                assert "Secret Project" not in w, f"warning 不应含目录名: {w}"
                assert "private file" not in w, f"warning 不应含文件名: {w}"
                assert "classified" not in w, f"warning 不应含文件内容: {w}"
                # 应使用固定安全错误信息
                assert "磁盘文件清理失败" in w, f"warning 应使用固定信息: {w}"
        finally:
            locked_file.chmod(stat_module.S_IWRITE)


# ═══════════════════════════════════════════════════════════════════════
# 5. 事务安全 — 真实 DELETE API
# ═══════════════════════════════════════════════════════════════════════

class TestTransactionSafety:
    def test_db_commit_failure_preserves_data(self, client, db_session, monkeypatch):
        """数据库提交失败时，API 不返回成功，Workspace/关联记录/文件均保留。"""
        _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "事务测试")

        uploaded = _upload_file(client, ws_id, h, "tx.csv", b"a,b\n1,2\n")
        fid = uploaded["file_id"]
        file_record = db_session.get(File, fid)
        phys = Path(file_record.file_path)
        assert phys.is_file()
        assert db_session.get(Workspace, ws_id) is not None

        # 注入 SQLAlchemy Session.commit 失败
        from sqlalchemy.orm import Session as SASession
        original_commit = SASession.commit

        def _failing_commit(self):
            raise RuntimeError("模拟数据库提交失败")

        monkeypatch.setattr(SASession, "commit", _failing_commit)

        try:
            r = _del(client, ws_id, "事务测试", h)
            # 如果 API 返回了响应（非异常传播），必须不是 200
            assert r.status_code != 200, (
                f"DB 提交失败不应返回成功，实际: {r.status_code}, body: {r.text[:200]}"
            )
            assert "项目已永久删除" not in r.text
        except RuntimeError:
            # endpoint 在 try/except 中 rollback 后 re-raise，异常向上传播
            # 这是预期行为，表示 API 没有吞掉错误
            pass
        finally:
            monkeypatch.setattr(SASession, "commit", original_commit)

        # 使用独立 session 验证数据完整性
        db_session.expire_all()
        assert db_session.get(Workspace, ws_id) is not None, "Workspace 应仍存在"
        assert db_session.get(File, fid) is not None, "File 应仍存在"
        assert phys.is_file(), "上传物理文件应仍存在"

        # WorkspaceFile 关联仍存在
        wf_count = db_session.scalar(
            select(func.count()).select_from(WorkspaceFile).where(
                WorkspaceFile.workspace_id == ws_id
            )
        )
        assert wf_count >= 1, "WorkspaceFile 关联应仍存在"


# ═══════════════════════════════════════════════════════════════════════
# 6. 配额回收
# ═══════════════════════════════════════════════════════════════════════

class TestQuotaReclaim:
    def test_orphan_file_reclaims_storage(self, client, db_session):
        """孤儿文件永久删除后 file_storage_bytes 减少。"""
        user = _add_user(db_session)
        h = _login(client)
        ws_id = _create_ws(client, h, "配额测试")

        _upload_file(client, ws_id, h, "quota.csv", b"col1,col2\nval1,val2\n")

        today = date.today()
        from sqlalchemy import select as sa_select
        counter_before = db_session.scalar(
            sa_select(UsageCounter).where(
                UsageCounter.user_id == user.id,
                UsageCounter.usage_date == today,
            )
        )
        before_bytes = counter_before.file_storage_bytes if counter_before else 0
        assert before_bytes > 0, "上传后应有配额记录"

        r = _del(client, ws_id, "配额测试", h)
        assert r.status_code == 200
        assert r.json()["deleted_counts"]["files_deleted"] == 1

        db_session.refresh(counter_before)
        assert counter_before.file_storage_bytes < before_bytes, (
            f"配额应减少：{counter_before.file_storage_bytes} >= {before_bytes}"
        )
        assert counter_before.file_storage_bytes >= 0, "配额不应小于 0"

    def test_shared_file_no_quota_reclaim(self, client, db_session):
        """共享文件被保留时不应回收配额。"""
        user = _add_user(db_session)
        h = _login(client)
        ws1 = _create_ws(client, h, "配额共享源")
        ws2 = _create_ws(client, h, "配额共享目标")

        uploaded = _upload_file(client, ws1, h, "shared-quota.csv", b"k,v\n1,2\n")
        fid = uploaded["file_id"]

        wf2 = WorkspaceFile(workspace_id=ws2, file_id=fid)
        db_session.add(wf2)
        db_session.commit()

        today = date.today()
        from sqlalchemy import select as sa_select
        counter_before = db_session.scalar(
            sa_select(UsageCounter).where(
                UsageCounter.user_id == user.id,
                UsageCounter.usage_date == today,
            )
        )
        before_bytes = counter_before.file_storage_bytes if counter_before else 0

        r = _del(client, ws1, "配额共享源", h)
        assert r.status_code == 200
        assert r.json()["deleted_counts"]["files_preserved_shared"] == 1
        assert r.json()["deleted_counts"]["files_deleted"] == 0

        db_session.refresh(counter_before)
        assert counter_before.file_storage_bytes == before_bytes, (
            f"共享文件不应回收配额：{counter_before.file_storage_bytes} != {before_bytes}"
        )
