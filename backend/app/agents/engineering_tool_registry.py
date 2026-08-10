"""工程 Verification Agent 专用工具注册表（阶段 4C-2）。

与旧 general Tool Registry（app.agents.tool_registry）完全独立，不扩展其职责。

只注册两个工具：
- engineering_hybrid_retrieval：对工作区执行 bm25/dense/hybrid_rrf 检索
- engineering_retrieval_index_prepare：构建/准备检索索引

安全约束：
- 只允许 engineering_verification_agent
- 输入 Schema 一律 extra="forbid"
- 每次调用先写 ReviewToolCall(status=running)，成功或失败均补全 trace
- 工具预算耗尽返回稳定错误码 ENGINEERING_VERIFICATION_BUDGET_EXCEEDED
- 不允许模型生成任意工具名（工具名由服务代码固定选择）
- 不提供 Shell / Python / SQL / URL / 文件路径类工具
- 输出做长度限制，但保留 locator、hash、rank 和 score
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.models.review_tool_call import ReviewToolCall
from app.models.review_verification_run import ReviewVerificationRun
from app.retrieval.errors import EngineeringRetrievalError
from app.services.engineering_retrieval_service import (
    rebuild_index,
    search_workspace,
)
from app.services.workspace_service import safe_public_text

ALLOWED_AGENT_TYPE = "engineering_verification_agent"

# 固定工具名（不允许模型生成）
ENGINEERING_TOOL_HYBRID_RETRIEVAL = "engineering_hybrid_retrieval"
ENGINEERING_TOOL_INDEX_PREPARE = "engineering_retrieval_index_prepare"
ENGINEERING_TOOL_NAMES = frozenset(
    {ENGINEERING_TOOL_HYBRID_RETRIEVAL, ENGINEERING_TOOL_INDEX_PREPARE}
)


class EngineeringToolError(Exception):
    """工程工具执行统一异常（带稳定错误码）。"""

    def __init__(self, code: str, message: str, status_code: int = 500):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class EngineeringHybridRetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: int = Field(ge=1)
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    retrieval_mode: Literal["bm25", "dense", "hybrid_rrf"] = "hybrid_rrf"
    reason: str = Field(min_length=1, max_length=500)


class EngineeringRetrievalIndexPrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rebuild: bool = False
    reason: str = Field(min_length=1, max_length=500)


ENGINEERING_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    ENGINEERING_TOOL_HYBRID_RETRIEVAL: {
        "description": "对工程工作区执行混合检索（bm25/dense/hybrid_rrf）",
        "input_schema": EngineeringHybridRetrievalInput,
        "timeout_seconds": 60,
        "idempotent": True,
    },
    ENGINEERING_TOOL_INDEX_PREPARE: {
        "description": "构建或复用工程工作区检索索引",
        "input_schema": EngineeringRetrievalIndexPrepareInput,
        "timeout_seconds": 300,
        "idempotent": True,
    },
}


def get_engineering_tool_definition(tool_name: str) -> dict[str, Any]:
    """按固定工具名获取定义；未知工具名直接拒绝（不允许模型生成工具名）。"""
    definition = ENGINEERING_TOOL_DEFINITIONS.get(tool_name)
    if definition is None:
        raise EngineeringToolError(
            "ENGINEERING_VERIFICATION_UNKNOWN_TOOL",
            "不允许调用未注册的工具",
            status_code=400,
        )
    return definition


def validate_engineering_agent_tool(agent_type: str, tool_name: str) -> dict[str, Any]:
    """权限校验：只允许 engineering_verification_agent。"""
    if agent_type != ALLOWED_AGENT_TYPE:
        raise EngineeringToolError(
            "ENGINEERING_VERIFICATION_PERMISSION_DENIED",
            "当前 Agent 无权调用工程工具",
            status_code=403,
        )
    return get_engineering_tool_definition(tool_name)


# ── ToolCall trace 写入（只追加） ────────────────────────────────────


def start_tool_call(
    db: Session,
    *,
    verification_run: ReviewVerificationRun,
    review_run_id: int,
    review_finding_id: int | None,
    workspace_id: int,
    owner_user_id: int,
    node_name: str,
    tool_name: str,
    attempt_number: int,
    retry_of_id: int | None,
    input_json: str,
) -> ReviewToolCall:
    record = ReviewToolCall(
        verification_run_id=verification_run.id,
        review_run_id=review_run_id,
        review_finding_id=review_finding_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        node_name=node_name,
        tool_name=tool_name,
        attempt_number=attempt_number,
        retry_of_id=retry_of_id,
        status="running",
        input_json=input_json,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _safe_output(value: dict[str, Any]) -> dict[str, Any]:
    """对工具输出做长度限制，保留 locator、hash、rank 和 score。"""
    result = dict(value)
    results = result.get("results")
    if isinstance(results, list):
        trimmed = []
        for item in results:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            quote = str(entry.get("quote", ""))
            if len(quote) > 300:
                entry["quote"] = quote[:300] + "…"
            trimmed.append(entry)
        result["results"] = trimmed
    return result


def complete_tool_call(
    db: Session,
    record: ReviewToolCall,
    *,
    status: str,
    output_json: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    latency_ms: int | None = None,
    index_sha256: str | None = None,
    corpus_sha256: str | None = None,
    model_revision: str | None = None,
) -> ReviewToolCall:
    record.status = status
    record.output_json = output_json
    record.error_code = error_code
    record.error_message = safe_public_text(error_message) if error_message else None
    record.latency_ms = latency_ms
    record.index_sha256 = index_sha256
    record.corpus_sha256 = corpus_sha256
    record.model_revision = model_revision
    from app.core.timeutils import utcnow
    record.completed_at = utcnow()
    db.commit()
    db.refresh(record)
    return record


# ── 工具执行 ────────────────────────────────────────────────────────


def _check_budget(verification_run: ReviewVerificationRun) -> None:
    if verification_run.tool_calls_used >= verification_run.tool_budget:
        raise EngineeringToolError(
            "ENGINEERING_VERIFICATION_BUDGET_EXCEEDED",
            "工具预算已耗尽",
            status_code=400,
        )


def execute_engineering_tool(
    db: Session,
    *,
    agent_type: str,
    tool_name: str,
    input_data: dict[str, Any],
    verification_run: ReviewVerificationRun,
    review_run_id: int,
    review_finding_id: int | None,
    workspace_id: int,
    owner_user_id: int,
    node_name: str,
    attempt_number: int = 1,
    retry_of_id: int | None = None,
) -> tuple[dict[str, Any], ReviewToolCall]:
    """校验权限 → 预算 → 写 running trace → 执行 → 补全 trace。

    返回 (output, tool_call_record)。执行失败不抛出，而是把失败结果写入
    ToolCall 并返回 {"status": "failed", "error_code": ...}。
    """
    definition = validate_engineering_agent_tool(agent_type, tool_name)
    _check_budget(verification_run)

    schema: type[BaseModel] = definition["input_schema"]
    try:
        validated = schema.model_validate(input_data)
    except Exception as e:
        raise EngineeringToolError(
            "ENGINEERING_VERIFICATION_INPUT_INVALID",
            f"工具输入校验失败: {e}",
            status_code=422,
        )

    import json as json_mod

    record = start_tool_call(
        db,
        verification_run=verification_run,
        review_run_id=review_run_id,
        review_finding_id=review_finding_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        node_name=node_name,
        tool_name=tool_name,
        attempt_number=attempt_number,
        retry_of_id=retry_of_id,
        input_json=json_mod.dumps(validated.model_dump(), ensure_ascii=False)[:8000],
    )

    t0 = time.perf_counter()
    try:
        if tool_name == ENGINEERING_TOOL_HYBRID_RETRIEVAL:
            assert isinstance(validated, EngineeringHybridRetrievalInput)
            response = search_workspace(
                db,
                workspace_id,
                owner_user_id,
                validated.query,
                top_k=validated.top_k,
                retrieval_mode=validated.retrieval_mode,
            )
            output = response.to_dict()
            # 候选证据边界：检索命中只能作为候选，须人工确认
            output["candidate_only"] = True
            output["requires_human_confirmation"] = True
        elif tool_name == ENGINEERING_TOOL_INDEX_PREPARE:
            assert isinstance(validated, EngineeringRetrievalIndexPrepareInput)
            output = rebuild_index(
                db,
                workspace_id,
                owner_user_id,
                rebuild=validated.rebuild,
            )
        else:  # pragma: no cover — get_engineering_tool_definition 已拒绝未知名
            raise EngineeringToolError(
                "ENGINEERING_VERIFICATION_UNKNOWN_TOOL", "未注册的工具", 400
            )
    except EngineeringRetrievalError as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        complete_tool_call(
            db, record,
            status="failed",
            error_code=e.code,
            error_message=e.message,
            latency_ms=latency_ms,
        )
        verification_run.tool_calls_used += 1
        db.commit()
        return {
            "status": "failed",
            "error_code": e.code,
            "message": safe_public_text(e.message),
        }, record
    except EngineeringToolError as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        complete_tool_call(
            db, record,
            status="failed",
            error_code=e.code,
            error_message=e.message,
            latency_ms=latency_ms,
        )
        verification_run.tool_calls_used += 1
        db.commit()
        return {
            "status": "failed",
            "error_code": e.code,
            "message": safe_public_text(e.message),
        }, record
    except Exception as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        complete_tool_call(
            db, record,
            status="failed",
            error_code="ENGINEERING_VERIFICATION_TOOL_ERROR",
            error_message="工具执行失败",
            latency_ms=latency_ms,
        )
        verification_run.tool_calls_used += 1
        db.commit()
        return {
            "status": "failed",
            "error_code": "ENGINEERING_VERIFICATION_TOOL_ERROR",
            "message": "工具执行失败",
        }, record

    latency_ms = int((time.perf_counter() - t0) * 1000)
    safe_out = _safe_output(output)
    complete_tool_call(
        db, record,
        status="success",
        output_json=json_mod.dumps(safe_out, ensure_ascii=False)[:30000],
        latency_ms=latency_ms,
        index_sha256=safe_out.get("index_sha256"),
        corpus_sha256=safe_out.get("corpus_sha256"),
        model_revision=safe_out.get("model_revision"),
    )
    verification_run.tool_calls_used += 1
    db.commit()
    return safe_out, record
