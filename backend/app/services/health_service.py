import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.db.session import SessionLocal
from app.models.operations import WorkerStatus


UNSUPPORTED_PRODUCTION_MODELS = {
    "",
    "deepseek-chat",
    "deepseek-reasoner",
    "replace_with_supported_model_name",
}


def model_configuration_issue() -> str | None:
    if not settings.llm_enabled:
        return "DeepSeek 已关闭，系统使用确定性降级模式"
    if (
        not settings.llm_api_key.strip()
        or settings.llm_api_key.strip().lower().startswith(("replace_", "your_"))
    ):
        return "DeepSeek API Key 未配置"
    if settings.llm_model.strip().lower() in UNSUPPORTED_PRODUCTION_MODELS:
        return "DeepSeek 模型未配置或仍使用已淘汰的生产模型名"
    if not settings.llm_base_url.strip().lower().startswith("https://"):
        return "DeepSeek API Base 必须使用 HTTPS"
    return None


def readiness_details(db: Session) -> dict:
    checks: dict[str, dict] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception:
        checks["database"] = {"status": "failed", "message": "数据库不可连接"}

    try:
        current, head = database_revisions(db)
        checks["migration"] = {
            "status": "ok" if current == head else "failed",
            "current": current,
            "head": head,
        }
    except Exception:
        checks["migration"] = {"status": "failed", "message": "无法检查数据库版本"}

    checks["storage"] = _storage_check()
    stale_after = datetime.utcnow() - timedelta(seconds=max(1, settings.worker_stale_seconds))
    worker = db.query(WorkerStatus).order_by(WorkerStatus.last_heartbeat_at.desc()).first()
    checks["worker"] = {
        "status": (
            "ok"
            if worker is not None and worker.last_heartbeat_at >= stale_after
            else "failed"
        ),
        "heartbeat_recent": bool(worker and worker.last_heartbeat_at >= stale_after),
    }
    checks["configuration"] = {
        "status": "ok",
        "legacy_v1_enabled": settings.enable_legacy_v1_api,
        "environment": settings.env,
    }
    model_issue = model_configuration_issue()
    checks["deepseek"] = {
        "status": "degraded" if model_issue else "ok",
        **({"message": model_issue} if model_issue else {}),
        "model": settings.llm_model if not model_issue else None,
    }
    tesseract = settings.tesseract_cmd or shutil.which("tesseract")
    checks["ocr"] = {"status": "ok" if tesseract else "degraded"}
    required_failed = any(
        checks[name]["status"] == "failed"
        for name in ("database", "migration", "storage", "worker", "configuration")
    )
    degraded = any(item["status"] == "degraded" for item in checks.values())
    return {
        "status": "not_ready" if required_failed else ("degraded" if degraded else "ready"),
        "checks": checks,
    }


def database_revisions(db: Session) -> tuple[str | None, str]:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    current = MigrationContext.configure(db.connection()).get_current_revision()
    return current, head


def _storage_check() -> dict:
    directories = []
    for raw in (settings.upload_dir, settings.chart_dir, settings.report_dir):
        path = Path(raw)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        directories.append(path)
    try:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f".health-{uuid.uuid4().hex}"
            probe.write_bytes(b"ok")
            probe.unlink()
    except Exception:
        return {"status": "failed", "message": "storage 不可写"}
    return {"status": "ok"}


def validate_production_runtime() -> None:
    """在生产启动阶段阻止数据库迁移或存储配置不安全的实例上线。"""
    if settings.env.lower() != "production":
        return
    with SessionLocal() as db:
        try:
            db.execute(text("SELECT 1"))
            current, head = database_revisions(db)
        except Exception as exc:
            raise RuntimeError("生产环境数据库连接或 Alembic revision 检查失败") from exc
    if current != head:
        raise RuntimeError("生产环境数据库 Alembic revision 不是当前 head")
    if _storage_check()["status"] != "ok":
        raise RuntimeError("生产环境 storage 不可写")
