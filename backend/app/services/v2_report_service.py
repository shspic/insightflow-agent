import json
from typing import Any
from pathlib import Path

from app.core.config import BACKEND_DIR, settings

from sqlalchemy.orm import Session

from app.models.task import Task
from app.services.report_template_service import get_report_template
from app.services.report_version_service import create_report_version

REQUIRED_REPORT_SECTIONS = list(
    get_report_template("comprehensive_analysis").required_sections
)


def _report_file(task_id: int) -> Path:
    """保留 V2-04 测试和外部调用使用的旧路径辅助函数。"""
    report_dir = Path(settings.report_dir)
    if not report_dir.is_absolute():
        report_dir = BACKEND_DIR / report_dir
    return report_dir / f"task_{task_id}_v2.md"


def generate_structured_report(
    db: Session,
    *,
    task: Task,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Report Agent 的兼容入口。

    V2-04 的任务字段继续保留，但规范正文和版本真相从 V2-05 起存储在 reports 表。
    """
    template_key = "comprehensive_analysis"
    preferences = state.get("report_preferences")
    if not isinstance(preferences, dict):
        try:
            preferences = json.loads(task.report_preferences_json or "{}")
        except json.JSONDecodeError:
            preferences = {}
    if isinstance(preferences, dict):
        template_key = str(preferences.get("template_key") or template_key)
    try:
        get_report_template(template_key)
    except ValueError:
        template_key = "comprehensive_analysis"

    generation_source = "initial"
    if task.report_id is not None:
        generation_source = (
            "retry" if int(state.get("retry_count") or 0) > 0 else "user_regenerate"
        )
    report = create_report_version(
        db,
        task=task,
        state=state,
        template_key=template_key,
        generation_source=generation_source,
    )
    return {
        "status": "completed",
        "report_id": report.id,
        "report_version": report.version,
        "template_key": report.template_key,
        "quality_status": report.quality_status,
        "content_summary": report.markdown_content[:2000],
        "reused": False,
    }
