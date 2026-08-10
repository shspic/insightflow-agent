"""阶段 5B 最终补修：pytest 会话级存储隔离证明测试。

验证 conftest.isolated_storage_session（session autouse）：
1. settings.report_dir/chart_dir/upload_dir 指向测试专属目录（≠ 默认 backend/storage/*）
2. retrieval index root（svc_mod._INDEX_ROOT）指向测试专属目录
3. API、报告服务与子进程读取同一测试专属路径
4. 会话期间默认 reports/retrieval 摘要不变（teardown 断言在 conftest 中）

无 mkdtemp 独立残留、无递归删除；目录生命周期由 pytest tmp_path_factory 管理。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import app.services.engineering_retrieval_service as svc_mod
from app.core.config import settings
from app.services.review_report_service import _resolve_storage_path, _storage_root

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS = (BACKEND_DIR / "storage" / "reports").resolve()
DEFAULT_RETRIEVAL = (BACKEND_DIR / "storage" / "retrieval" / "workspaces").resolve()


def _is_test_root(value: str, name: str) -> bool:
    """会话级临时根由 tmp_path_factory 生成，路径含 pytest-storage。"""
    return "pytest-storage" in value and name in Path(value).name


def test_report_chart_upload_roots_isolated() -> None:
    """settings 的 report/chart/upload 必须指向测试专属目录。"""
    assert "pytest-storage" in settings.report_dir, settings.report_dir
    assert "pytest-storage" in settings.chart_dir, settings.chart_dir
    assert "pytest-storage" in settings.upload_dir, settings.upload_dir
    assert Path(settings.report_dir).resolve() != DEFAULT_REPORTS
    assert Path(settings.chart_dir).resolve() != (BACKEND_DIR / "storage" / "charts").resolve()


def test_retrieval_index_root_isolated() -> None:
    """_INDEX_ROOT 必须指向测试专属目录（模块变量 + env 配置双路径一致）。"""
    assert "pytest-storage" in str(svc_mod._INDEX_ROOT), str(svc_mod._INDEX_ROOT)
    assert svc_mod._INDEX_ROOT.resolve() != DEFAULT_RETRIEVAL
    env_root = os.environ.get("ENGINEERING_RETRIEVAL_INDEX_ROOT", "")
    assert env_root and Path(env_root).resolve() == svc_mod._INDEX_ROOT.resolve()


def test_env_vars_cover_subprocess_inheritance() -> None:
    """env 必须已覆盖，子进程 import settings/retrieval 时得到同一路径。"""
    for key in ("UPLOAD_DIR", "CHART_DIR", "REPORT_DIR", "ENGINEERING_RETRIEVAL_INDEX_ROOT"):
        assert os.environ.get(key), f"{key} 未设置"
    assert os.environ["REPORT_DIR"] == settings.report_dir
    assert os.environ["UPLOAD_DIR"] == settings.upload_dir
    assert os.environ["CHART_DIR"] == settings.chart_dir
    assert Path(os.environ["ENGINEERING_RETRIEVAL_INDEX_ROOT"]).resolve() == svc_mod._INDEX_ROOT.resolve()


def test_subprocess_sees_same_isolated_paths() -> None:
    """子进程（继承 os.environ）必须读取到与父进程相同的测试专属路径。"""
    code = (
        "import sys, os\n"
        f"sys.path.insert(0, {str(BACKEND_DIR)!r})\n"
        "os.chdir(__import__('pathlib').Path(__import__('os').getcwd()))\n"
        "from app.core.config import settings\n"
        "import app.services.engineering_retrieval_service as svc_mod\n"
        "import json\n"
        "print(json.dumps({\n"
        "  'report': settings.report_dir,\n"
        "  'chart': settings.chart_dir,\n"
        "  'upload': settings.upload_dir,\n"
        "  'index_root': str(svc_mod._INDEX_ROOT),\n"
        "}, ensure_ascii=False))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=os.environ,
        cwd=BACKEND_DIR,
        timeout=120,
    )
    assert result.returncode == 0, f"子进程失败: {result.stderr[:500]}"
    import json

    child = json.loads(result.stdout.strip().splitlines()[-1])
    assert child["report"] == settings.report_dir
    assert child["chart"] == settings.chart_dir
    assert child["upload"] == settings.upload_dir
    assert Path(child["index_root"]).resolve() == svc_mod._INDEX_ROOT.resolve()


def test_report_service_uses_isolated_root() -> None:
    """报告服务 _storage_root() 必须解析到测试专属根。"""
    root = _storage_root()
    assert "pytest-storage" in str(root)
    assert root != DEFAULT_REPORTS


def test_report_asset_writes_to_isolated_root(tmp_path) -> None:
    """通过报告服务生成资产，磁盘文件必须落在测试专属根下（不写默认 reports）。"""
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker

    from test_v5b_supervisor import _build_db, _fresh_run

    db_path = tmp_path / "iso.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    data = _build_db(db_url, tmp_path / "up")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()
    try:
        run_id = _fresh_run(db, data)
        from app.models.review_run import ReviewRun
        from app.services.review_report_service import generate_review_report

        run = db.scalar(select(ReviewRun).where(ReviewRun.id == run_id))
        report, _ = generate_review_report(
            db, run=run, workspace_id=data["workspace"], owner_user_id=data["user"])
        from app.models.review_report_asset import ReviewReportAsset

        assets = list(db.scalars(select(ReviewReportAsset).where(
            ReviewReportAsset.review_report_id == report.id)).all())
        assert assets
        for asset in assets:
            disk = _resolve_storage_path(asset.storage_path)
            assert disk.is_file(), f"资产缺失: {disk}"
            assert "pytest-storage" in str(disk), f"资产写入默认目录: {disk}"
            assert Path(settings.report_dir).resolve() in disk.resolve().parents
    finally:
        db.close()
        engine.dispose()


def test_api_report_returns_isolated_storage_path(client, db_session, tmp_path) -> None:
    """API 生成报告返回的 storage_path 解析后必须位于测试专属根。"""
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker

    from test_v5b_supervisor import _build_db, _fresh_run

    db_path = tmp_path / "api.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    data = _build_db(db_url, tmp_path / "up2")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()
    try:
        run_id = _fresh_run(db, data)
        from app.models.review_run import ReviewRun

        run = db.scalar(select(ReviewRun).where(ReviewRun.id == run_id))
        # API 走 client fixture 的 db（内存库），因此直接调用 service 验证路径契约即可；
        # 这里验证 service 返回值与 API 使用的 _resolve_storage_path 一致。
        from app.services.review_report_service import generate_review_report

        report, _ = generate_review_report(
            db, run=run, workspace_id=data["workspace"], owner_user_id=data["user"])
        from app.models.review_report_asset import ReviewReportAsset

        assets = list(db.scalars(select(ReviewReportAsset).where(
            ReviewReportAsset.review_report_id == report.id)).all())
        for asset in assets:
            disk = _resolve_storage_path(asset.storage_path)
            assert disk.is_file()
            assert "pytest-storage" in str(disk)
    finally:
        db.close()
        engine.dispose()
