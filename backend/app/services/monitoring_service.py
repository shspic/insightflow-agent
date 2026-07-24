from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.models.operations import WorkerStatus
from app.models.task import Task
from app.models.tool_call import ToolCall
from app.models.usage import ModelUsageRecord


def operational_summary(db: Session) -> dict[str, Any]:
    tasks = list(db.scalars(select(Task)).all())
    status_distribution: dict[str, int] = defaultdict(int)
    queue_times: list[int] = []
    durations: list[int] = []
    for task in tasks:
        status_distribution[task.status] += 1
        if task.queued_at and task.started_at:
            queue_times.append(max(0, int((task.started_at - task.queued_at).total_seconds() * 1000)))
        if task.started_at and task.completed_at:
            durations.append(max(0, int((task.completed_at - task.started_at).total_seconds() * 1000)))
    total = max(1, len(tasks))
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "tasks": {
            "total": len(tasks),
            "status_distribution": dict(status_distribution),
            "average_queue_ms": _average(queue_times),
            "average_duration_ms": _average(durations),
            "p95_duration_ms": _percentile(durations, 0.95),
            "failure_rate": round(status_distribution["failed"] / total, 4),
            "cancellation_rate": round(status_distribution["cancelled"] / total, 4),
            "retry_rate": round(sum(task.retry_count > 0 for task in tasks) / total, 4),
            "completed_with_warnings_rate": round(
                status_distribution["completed_with_warnings"] / total, 4
            ),
        },
        "agents": _agent_metrics(db),
        "tools": _tool_metrics(db),
        "models": _model_metrics(db),
    }


def _agent_metrics(db: Session) -> list[dict[str, Any]]:
    records = list(db.scalars(select(AgentRun)).all())
    groups: dict[str, list[AgentRun]] = defaultdict(list)
    for item in records:
        groups[item.agent_type].append(item)
    return [
        {
            "agent_type": name,
            "calls": len(items),
            "success_rate": round(sum(item.status == "completed" for item in items) / len(items), 4),
            "average_duration_ms": _average([item.duration_ms or 0 for item in items]),
            "fallback_count": sum(bool(item.fallback_used) for item in items),
            "review_block_count": sum(item.error_code == "QUALITY_REVIEW_FAILED" for item in items),
            "retry_count": sum(item.run_number > 1 for item in items),
        }
        for name, items in sorted(groups.items())
    ]


def _tool_metrics(db: Session) -> list[dict[str, Any]]:
    records = list(db.scalars(select(ToolCall)).all())
    groups: dict[str, list[ToolCall]] = defaultdict(list)
    for item in records:
        groups[item.tool_name or "unknown"].append(item)
    return [
        {
            "tool_name": name,
            "calls": len(items),
            "error_rate": round(sum(item.status == "failed" for item in items) / len(items), 4),
            "average_duration_ms": _average([item.latency_ms or 0 for item in items]),
            "timeout_count": sum(
                "timeout" in str(item.error_message or "").casefold() for item in items
            ),
        }
        for name, items in sorted(groups.items())
    ]


def _model_metrics(db: Session) -> dict[str, Any]:
    records = list(db.scalars(select(ModelUsageRecord)).all())
    total = len(records)
    return {
        "calls": total,
        "success_rate": round(sum(item.status == "success" for item in records) / max(1, total), 4),
        "timeout_count": sum(item.error_code == "MODEL_TIMEOUT" for item in records),
        "invalid_structured_output_count": sum(
            item.error_code == "INVALID_STRUCTURED_OUTPUT" for item in records
        ),
        "input_tokens": sum(item.input_tokens for item in records),
        "output_tokens": sum(item.output_tokens for item in records),
        "estimated_cost_micros": sum(item.estimated_cost_micros for item in records),
        "average_duration_ms": _average([item.duration_ms for item in records]),
    }


def _average(values: list[int]) -> int:
    return int(sum(values) / len(values)) if values else 0


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999) - 1))]
