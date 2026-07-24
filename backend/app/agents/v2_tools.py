import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from app.agents.tool_registry import (
    DataAnalysisInput,
    DocumentRetrievalInput,
    FileIdsInput,
    QualityReviewInput,
    ReportToolInput,
    ToolContext,
    ToolExecutionError,
)
from app.core.config import BACKEND_DIR, settings
from app.models.file import File
from app.models.file_chunk import FileChunk
from app.models.agent_run import AgentRun
from app.models.report import Report
from app.models.task_step import TaskStep
from app.models.usage import ModelUsageRecord
from app.models.user import User
from app.schemas.task_execution import QualityReviewOutput
from app.services.analysis_service import _build_analysis_result
from app.services.chart_service import generate_charts
from app.services.llm_service import call_llm, is_llm_ready, safe_json_dumps
from app.services.quota_service import QuotaExceeded, check_model_call, increment_usage
from app.services.rag_service import answer_pdf_question
from app.services.v2_report_service import REQUIRED_REPORT_SECTIONS, generate_structured_report
from app.services.workspace_context_service import build_workspace_context


TABLE_TYPES = {"csv", "xlsx"}
DOCUMENT_TYPES = {"pdf", "md", "markdown"}
MAX_ANALYSIS_ROWS = 100_000


def run_workspace_context_lookup(
    context: ToolContext,
    payload: FileIdsInput,
) -> dict[str, Any]:
    workspace_context = build_workspace_context(
        context.db,
        workspace_id=context.task.workspace_id,
        owner_user_id=context.task.owner_user_id,
        selected_file_ids=payload.file_ids,
    )
    return {
        "status": "completed",
        "workspace_context": workspace_context.model_dump(),
        "confirmed_relations": workspace_context.confirmed_relations,
        "unready_files": workspace_context.unready_files,
    }


def run_multi_table_analysis(
    context: ToolContext,
    payload: DataAnalysisInput,
) -> dict[str, Any]:
    files = _owned_files(context, payload.file_ids, allowed_types=TABLE_TYPES)
    findings: list[dict[str, Any]] = []
    chart_assets: list[dict[str, Any]] = []
    warnings: list[str] = []
    for file_record in files:
        frames = _read_frames(file_record)
        for sheet_name, dataframe in frames.items():
            sampled = len(dataframe) > MAX_ANALYSIS_ROWS
            working = dataframe.head(MAX_ANALYSIS_ROWS) if sampled else dataframe
            result = _build_analysis_result(working)
            result.pop("preview_rows", None)
            findings.append(
                {
                    "file_id": file_record.id,
                    "filename": file_record.filename,
                    "sheet_name": sheet_name,
                    "source_row_count": int(len(dataframe)),
                    "analyzed_row_count": int(len(working)),
                    "duplicate_row_count": int(working.duplicated().sum()),
                    "sampled": sampled,
                    "calculation_method": (
                        "Pandas 预设统计：字段类型、缺失值、重复值、数值 count/mean/min/max/sum、"
                        "文本 Top 5；未执行用户代码"
                    ),
                    "result": result,
                }
            )
            if sampled:
                warnings.append(
                    f"{file_record.filename}/{sheet_name} 超过 {MAX_ANALYSIS_ROWS} 行，使用前序样本分析。"
                )
        if payload.generate_charts:
            charted = generate_charts(context.db, file_record)
            schema = _json_dict(charted.schema_json)
            for chart in schema.get("charts", []):
                asset_name = None
                if chart.get("file_path"):
                    asset_name = Path(chart["file_path"]).name
                chart_assets.append(
                    {
                        "file_id": file_record.id,
                        "filename": file_record.filename,
                        "title": chart.get("title"),
                        "chart_type": chart.get("chart_type"),
                        "asset_name": asset_name,
                        "skipped": bool(chart.get("skipped")),
                        "description": chart.get("description"),
                    }
                )
    return {
        "status": "completed",
        "findings": findings,
        "chart_assets": chart_assets,
        "warnings": warnings,
    }


def run_document_retrieval(
    context: ToolContext,
    payload: DocumentRetrievalInput,
) -> dict[str, Any]:
    files = _owned_files(context, payload.file_ids, allowed_types=DOCUMENT_TYPES)
    evidence: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for file_record in files:
        if file_record.file_type == "pdf":
            result = answer_pdf_question(
                db=context.db,
                file_record=file_record,
                question=payload.query,
                top_k=payload.top_k,
                retrieval_mode=payload.retrieval_mode,
            )
            for source in result.get("sources", []):
                evidence.append(
                    {
                        "file_id": file_record.id,
                        "filename": file_record.filename,
                        "page_number": source.get("page_number"),
                        "section_path": None,
                        "char_start": None,
                        "char_end": None,
                        "chunk_id": source.get("chunk_id"),
                        "snippet": str(source.get("chunk_text") or "")[:300],
                        "score": source.get("score"),
                        "retrieval_mode": source.get("retrieval_mode"),
                    }
                )
            traces.append(
                {
                    "file_id": file_record.id,
                    "retrieval_mode": result.get("retrieval_mode"),
                    "top_k": result.get("top_k"),
                    "result_count": result.get("result_count"),
                    "fallback_used": result.get("fallback_used", False),
                }
            )
        else:
            matches = _search_markdown_chunks(
                context,
                file_record,
                payload.query,
                payload.top_k,
            )
            evidence.extend(matches)
            traces.append(
                {
                    "file_id": file_record.id,
                    "retrieval_mode": "keyword",
                    "top_k": payload.top_k,
                    "result_count": len(matches),
                    "fallback_used": payload.retrieval_mode != "keyword",
                }
            )
    return {
        "status": "completed" if evidence else "evidence_not_found",
        "evidence": evidence,
        "retrieval_traces": traces,
        "warning": None if evidence else "evidence_not_found",
    }


def run_structured_report(
    context: ToolContext,
    payload: ReportToolInput,
) -> dict[str, Any]:
    if payload.task_id != context.task.id:
        raise ToolExecutionError("报告任务 ID 与当前任务不一致", "INVALID_TASK_SCOPE")
    return generate_structured_report(
        context.db,
        task=context.task,
        state=context.state.model_dump(),
    )


def run_quality_review(
    context: ToolContext,
    payload: QualityReviewInput,
) -> dict[str, Any]:
    if payload.task_id != context.task.id:
        raise ToolExecutionError("审核任务 ID 与当前任务不一致", "INVALID_TASK_SCOPE")
    deterministic = _deterministic_review(context)
    model_metadata = {
        "used": False,
        "fallback_used": bool(context.task.use_deepseek),
        "provider": settings.llm_provider,
        "model_name": settings.llm_model,
        "token_usage": None,
        "duration_ms": None,
    }
    if (
        deterministic.status in {"passed", "passed_with_warnings"}
        and context.task.use_deepseek
        and is_llm_ready()
        and context.state.model_budget > 0
    ):
        owner = context.db.get(User, context.task.owner_user_id)
        if owner is None:
            raise ToolExecutionError("任务所有者不存在", "USER_NOT_FOUND")
        try:
            check_model_call(context.db, owner, context.task)
        except QuotaExceeded as exc:
            raise ToolExecutionError(str(exc), "QUOTA_EXCEEDED") from exc
        context.state.model_budget -= 1
        model_review, model_result = _model_review(context)
        token_usage = model_result.token_usage or {}
        input_tokens = int(
            token_usage.get("prompt_tokens")
            or token_usage.get("input_tokens")
            or 0
        )
        output_tokens = int(
            token_usage.get("completion_tokens")
            or token_usage.get("output_tokens")
            or 0
        )
        agent_run = (
            context.db.get(AgentRun, context.agent_run_id)
            if context.agent_run_id is not None
            else None
        )
        context.db.add(
            ModelUsageRecord(
                user_id=owner.id,
                task_id=context.task.id,
                agent_run_id=context.agent_run_id,
                provider=settings.llm_provider,
                model_name=settings.llm_model,
                prompt_name=agent_run.prompt_name if agent_run else "quality_review",
                prompt_version=agent_run.prompt_version if agent_run else None,
                status="success" if model_result.success else "failed",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=int(model_result.duration_ms or 0),
                error_code=None if model_result.success else "MODEL_CALL_FAILED",
                metadata_json=json.dumps(
                    {"skipped": model_result.skipped},
                    ensure_ascii=False,
                ),
            )
        )
        increment_usage(
            context.db,
            owner.id,
            deepseek_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        model_metadata["token_usage"] = model_result.token_usage
        model_metadata["duration_ms"] = model_result.duration_ms
        if model_review is not None:
            deterministic = _merge_review(deterministic, model_review)
            model_metadata["used"] = True
            model_metadata["fallback_used"] = False
    return {
        "status": deterministic.status,
        "issues": deterministic.issues,
        "retry_step_ids": deterministic.retry_step_ids,
        "model_review": model_metadata,
    }


def _owned_files(
    context: ToolContext,
    file_ids: list[int],
    *,
    allowed_types: set[str],
) -> list[File]:
    records = list(
        context.db.scalars(
            select(File).where(
                File.id.in_(file_ids),
                File.owner_user_id == context.task.owner_user_id,
            )
        ).all()
    )
    mapping = {item.id: item for item in records}
    selected = [
        mapping[file_id]
        for file_id in file_ids
        if file_id in mapping and (mapping[file_id].file_type or "").lower() in allowed_types
    ]
    invalid_ids = [file_id for file_id in file_ids if file_id not in mapping]
    if invalid_ids:
        raise ToolExecutionError("包含无权访问或不存在的文件", "INVALID_FILE_SCOPE")
    return selected


def _read_frames(file_record: File) -> dict[str, pd.DataFrame]:
    file_path = Path(file_record.file_path)
    if not file_path.exists():
        raise ToolExecutionError("表格文件不存在", "FILE_NOT_FOUND")
    if file_record.file_type == "csv":
        return {"CSV": pd.read_csv(file_path)}
    return pd.read_excel(file_path, sheet_name=None)


def _search_markdown_chunks(
    context: ToolContext,
    file_record: File,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    chunks = list(
        context.db.scalars(
            select(FileChunk)
            .where(FileChunk.file_id == file_record.id)
            .order_by(FileChunk.chunk_index.asc())
        ).all()
    )
    tokens = _query_tokens(query)
    scored = []
    for chunk in chunks:
        compact = re.sub(r"\s+", " ", chunk.chunk_text).strip()
        score = sum(compact.lower().count(token) for token in tokens)
        if score <= 0:
            continue
        scored.append((score, chunk, compact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "file_id": file_record.id,
            "filename": file_record.filename,
            "page_number": None,
            "section_path": chunk.section_path,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "chunk_id": chunk.id,
            "snippet": compact[:300],
            "score": score,
            "retrieval_mode": "keyword",
        }
        for score, chunk, compact in scored[:top_k]
    ]


def _query_tokens(query: str) -> list[str]:
    lowered = query.lower()
    words = re.findall(r"[a-z0-9_]+", lowered)
    chinese = re.findall(r"[\u4e00-\u9fff]{1,4}", lowered)
    return list(dict.fromkeys(words + chinese)) or [lowered]


def _deterministic_review(context: ToolContext) -> QualityReviewOutput:
    issues: list[dict[str, Any]] = []
    retry_ids: list[int] = []
    steps = list(
        context.db.scalars(
            select(TaskStep)
            .where(TaskStep.task_id == context.task.id)
            .order_by(TaskStep.step_order.asc())
        ).all()
    )
    failed = [item for item in steps if item.status == "failed"]
    for step in failed:
        issues.append({"code": "FAILED_STEP", "message": f"步骤 {step.title} 失败", "step_id": step.id})
        retry_ids.append(step.id)
    incomplete = [
        item
        for item in steps
        if item.id != context.step.id and item.status not in {"completed", "skipped"}
    ]
    for step in incomplete:
        issues.append(
            {"code": "INCOMPLETE_STEP", "message": f"步骤 {step.title} 未完成", "step_id": step.id}
        )

    state = context.state
    if any(item.agent_type == "data_analysis_agent" for item in steps) and not state.analysis_findings:
        issues.append({"code": "MISSING_DATA_FINDINGS", "message": "缺少结构化数据结论"})
        retry_ids.extend(item.id for item in steps if item.agent_type == "data_analysis_agent")
    for citation in state.document_evidence:
        chunk = context.db.get(FileChunk, citation.get("chunk_id"))
        if (
            chunk is None
            or chunk.file_id != citation.get("file_id")
            or chunk.file_id not in state.selected_file_ids
            or chunk.page_number != citation.get("page_number")
            or chunk.section_path != citation.get("section_path")
        ):
            issues.append({"code": "INVALID_CITATION", "message": "引用定位无法在 file_chunks 中验证"})

    report_record = (
        context.db.get(Report, context.task.report_id)
        if context.task.report_id is not None
        else None
    )
    report_file = _resolve_report(context.task.report_path)
    if report_record is not None:
        content = report_record.markdown_content
    elif report_file is not None and report_file.exists():
        content = report_file.read_text(encoding="utf-8")
    else:
        content = None
    if content is None:
        issues.append({"code": "REPORT_NOT_FOUND", "message": "Markdown 报告资源不存在"})
        retry_ids.extend(item.id for item in steps if item.agent_type == "report_agent")
    else:
        for section in REQUIRED_REPORT_SECTIONS:
            if f"## {section}" not in content:
                issues.append({"code": "MISSING_REPORT_SECTION", "message": f"报告缺少章节：{section}"})
        if re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s<>\"]+", content):
            issues.append({"code": "LOCAL_PATH_EXPOSED", "message": "报告包含服务器本地路径"})

    for asset in state.chart_assets:
        if asset.get("skipped") or not asset.get("asset_name"):
            continue
        chart_dir = Path(settings.chart_dir)
        if not chart_dir.is_absolute():
            chart_dir = BACKEND_DIR / chart_dir
        if not (chart_dir / Path(asset["asset_name"]).name).exists():
            issues.append({"code": "CHART_NOT_FOUND", "message": f"图表资源不存在：{asset['asset_name']}"})

    retry_ids = list(dict.fromkeys(retry_ids))
    if retry_ids:
        return QualityReviewOutput(status="retry_required", issues=issues, retry_step_ids=retry_ids)
    if issues:
        return QualityReviewOutput(status="passed_with_warnings", issues=issues)
    return QualityReviewOutput(status="passed")


def _model_review(context: ToolContext):
    result = call_llm(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是质量审核器。只能基于提供的结构化摘要审核用户目标覆盖、结论一致性和限制。"
                    "返回 JSON：status、issues、retry_step_ids。status 只能是 passed、"
                    "retry_required、passed_with_warnings、failed。不得编造原文或页码。"
                ),
            },
            {
                "role": "user",
                "content": safe_json_dumps(
                    {
                        "goal": context.state.clarified_request,
                        "plan": context.state.current_plan,
                        "findings": context.state.analysis_findings,
                        "citations": context.state.document_evidence,
                        "report_sections": context.state.report_sections,
                    },
                    max_length=10000,
                ),
            },
        ],
        temperature=0,
        max_tokens=800,
    )
    if not result.success or not result.content:
        return None, result
    try:
        return QualityReviewOutput.model_validate_json(result.content), result
    except Exception:
        return None, result


def _merge_review(
    deterministic: QualityReviewOutput,
    model_review: QualityReviewOutput,
) -> QualityReviewOutput:
    if model_review.status == "passed":
        return deterministic
    return QualityReviewOutput(
        status=model_review.status,
        issues=deterministic.issues + model_review.issues,
        retry_step_ids=model_review.retry_step_ids,
    )


def _resolve_report(report_path: str | None) -> Path | None:
    if not report_path:
        return None
    path = Path(report_path)
    return path if path.is_absolute() else BACKEND_DIR / path


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
