import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.task import Task
from app.services.workspace_service import safe_public_text


REQUIRED_REPORT_SECTIONS = [
    "任务和文件概述",
    "用户目标",
    "分析方法",
    "数据结论",
    "数据质量问题",
    "异常和风险",
    "图表",
    "文档事实与引用",
    "多文件综合结论",
    "行动建议",
    "假设",
    "限制和不确定性",
]


def generate_structured_report(
    db: Session,
    *,
    task: Task,
    state: dict[str, Any],
) -> dict[str, Any]:
    report_file = _report_file(task.id)
    if task.report_path and report_file.exists():
        content = report_file.read_text(encoding="utf-8")
        return _result(task, content, reused=True)

    content = _build_content(task, state)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(content, encoding="utf-8")
    try:
        task.report_path = str(report_file.relative_to(BACKEND_DIR)).replace("\\", "/")
    except ValueError:
        task.report_path = str(report_file)
    task.report_id = task.report_id or task.id
    db.flush()
    return _result(task, content, reused=False)


def _build_content(task: Task, state: dict[str, Any]) -> str:
    context = state.get("workspace_context") or {}
    files = context.get("files") or []
    findings = state.get("analysis_findings") or []
    evidence = state.get("document_evidence") or []
    charts = state.get("chart_assets") or []
    assumptions = state.get("assumptions") or []
    warnings = state.get("warnings") or []
    methods = [
        item.get("calculation_method")
        for item in findings
        if item.get("calculation_method")
    ]
    sections = [
        "# InsightFlow 综合分析报告",
        "",
        "## 任务和文件概述",
        _bullets(
            [
                f"任务 ID：{task.id}",
                f"文件：{', '.join(str(item.get('filename')) for item in files) or '无'}",
                *[
                    (
                        f"{item.get('filename')}：角色={item.get('effective_role') or '未确认'}；"
                        f"摘要={item.get('summary') or '无'}；Profile={item.get('profile_status')}"
                    )
                    for item in files
                ],
            ]
        ),
        "",
        "## 用户目标",
        safe_public_text(state.get("clarified_request") or task.user_input) or "未提供",
        "",
        "## 分析方法",
        _bullets(methods or ["读取 V2-03 文件 Profile 与 Workspace Context", "执行受限预设工具"]),
        "",
        "## 数据结论",
        _json_blocks(findings, "未选择表格文件或未得到可复核的数据结论。"),
        "",
        "## 数据质量问题",
        _json_blocks(context.get("data_quality_issues") or [], "未记录数据质量问题。"),
        "",
        "## 异常和风险",
        _bullets(warnings or ["未记录额外风险；关键结论仍建议人工复核。"]),
        "",
        "## 图表",
        _chart_lines(charts),
        "",
        "## 文档事实与引用",
        _evidence_lines(evidence),
        "",
        "## 多文件综合结论",
        _synthesis(findings, evidence),
        "",
        "## 行动建议",
        _bullets(_recommendations(findings, evidence, warnings)),
        "",
        "## 假设",
        _bullets(assumptions or ["未记录额外假设。"]),
        "",
        "## 限制和不确定性",
        _bullets(
            [
                "只使用当前任务确认计划中选择的文件。",
                "OCR、文档检索、采样统计和模型组织可能存在误差。",
                "报告数字来自 Data Analysis Agent 的结构化结果，引用来自检索结果。",
            ]
        ),
        "",
    ]
    return "\n".join(sections)


def _report_file(task_id: int) -> Path:
    report_dir = Path(settings.report_dir)
    if not report_dir.is_absolute():
        report_dir = BACKEND_DIR / report_dir
    return report_dir / f"task_{task_id}_v2.md"


def _result(task: Task, content: str, *, reused: bool) -> dict[str, Any]:
    return {
        "status": "completed",
        "report_id": task.report_id or task.id,
        "sections": REQUIRED_REPORT_SECTIONS,
        "content_summary": content[:2000],
        "reused": reused,
    }


def _bullets(items: list[Any]) -> str:
    return "\n".join(f"- {safe_public_text(str(item))}" for item in items if item is not None)


def _json_blocks(items: list[dict[str, Any]], empty: str) -> str:
    if not items:
        return empty
    return "\n".join(
        f"- {json.dumps(item, ensure_ascii=False, default=str)}"
        for item in items
    )


def _chart_lines(charts: list[dict[str, Any]]) -> str:
    active = [item for item in charts if not item.get("skipped") and item.get("asset_name")]
    if not active:
        return "本任务未生成可用图表。"
    return "\n".join(
        f"- {item.get('title', '图表')}：`{item['asset_name']}`"
        for item in active
    )


def _evidence_lines(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "未找到与用户目标直接相关的文档证据。"
    lines = []
    for item in evidence:
        location = (
            f"第 {item['page_number']} 页"
            if item.get("page_number") is not None
            else item.get("section_path") or f"字符 {item.get('char_start', '?')}"
        )
        lines.append(
            f"- [{item.get('filename')}] {location}：{item.get('snippet', '')}"
        )
    return "\n".join(lines)


def _synthesis(findings: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> str:
    if findings and evidence:
        return "已将表格统计结论与文档检索证据并列呈现；没有已确认连接字段时不做自动行级拼接。"
    if findings:
        return "综合结论当前主要基于表格结构化统计。"
    if evidence:
        return "综合结论当前主要基于文档检索证据。"
    return "当前证据不足，无法形成可靠的跨文件综合结论。"


def _recommendations(
    findings: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    warnings: list[str],
) -> list[str]:
    items = ["优先复核数据质量问题、异常值和关键引用。"]
    if findings and evidence:
        items.append("如需行级关联，请确认连接字段和关系后重新生成计划。")
    if warnings:
        items.append("处理审核警告后再将报告用于正式决策。")
    return items
