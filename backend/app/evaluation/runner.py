import csv
import json
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation.dataset import load_v2_core_dataset
from app.models.evaluation import EvaluationCase, EvaluationResult, EvaluationRun


def run_evaluation(
    db: Session,
    *,
    dataset_name: str,
    mode: str,
    category: str | None = None,
) -> EvaluationRun:
    if dataset_name != "v2-core":
        raise ValueError("当前只提供 v2-core 数据集")
    if mode != "deterministic":
        raise ValueError("model 模式必须由显式启用模型的外层命令执行")
    dataset = load_v2_core_dataset(db)
    run = EvaluationRun(
        dataset_id=dataset.id,
        mode=mode,
        category_filter=category,
        status="running",
        prompt_versions_json=json.dumps({"registry": "2.05.1"}),
        model_version=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    statement = select(EvaluationCase).where(EvaluationCase.dataset_id == dataset.id)
    if category:
        statement = statement.where(EvaluationCase.category == category)
    cases = list(db.scalars(statement.order_by(EvaluationCase.case_key)).all())
    if not cases:
        run.status = "failed"
        run.error_message = "没有匹配的评估案例"
        run.completed_at = datetime.utcnow()
        db.commit()
        return run
    try:
        for case in cases:
            started = time.perf_counter()
            actual = _deterministic_execute(case)
            checks = _score_case(case, actual)
            errors = [name for name, passed in checks.items() if not passed]
            db.add(
                EvaluationResult(
                    run_id=run.id,
                    case_id=case.id,
                    status="passed" if not errors else "failed",
                    actual_result_json=json.dumps(actual, ensure_ascii=False),
                    metrics_json=json.dumps(checks, ensure_ascii=False),
                    errors_json=json.dumps(errors, ensure_ascii=False),
                    duration_ms=max(1, int((time.perf_counter() - started) * 1000)),
                    model_calls=0,
                    tool_calls=len(actual["tools"]),
                )
            )
        db.flush()
        results = list(
            db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)).all()
        )
        run.metrics_json = json.dumps(_aggregate_metrics(cases, results), ensure_ascii=False)
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        run = db.get(EvaluationRun, run.id)
        run.status = "failed"
        run.error_message = str(exc)[:500]
        run.completed_at = datetime.utcnow()
        db.commit()
        return run


def export_failures(db: Session, run_id: int, output: Path) -> int:
    rows = db.execute(
        select(EvaluationResult, EvaluationCase)
        .join(EvaluationCase, EvaluationCase.id == EvaluationResult.case_id)
        .where(EvaluationResult.run_id == run_id, EvaluationResult.status == "failed")
    ).all()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".csv":
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["case_key", "category", "input_task", "errors", "actual_result"],
            )
            writer.writeheader()
            for result, case in rows:
                writer.writerow(
                    {
                        "case_key": case.case_key,
                        "category": case.category,
                        "input_task": case.input_task,
                        "errors": result.errors_json,
                        "actual_result": result.actual_result_json,
                    }
                )
    else:
        output.write_text(
            json.dumps(
                [
                    {
                        "case_key": case.case_key,
                        "category": case.category,
                        "input_task": case.input_task,
                        "errors": json.loads(result.errors_json),
                        "actual_result": json.loads(result.actual_result_json),
                    }
                    for result, case in rows
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return len(rows)


def run_response(run: EvaluationRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "mode": run.mode,
        "category": run.category_filter,
        "metrics": json.loads(run.metrics_json or "{}"),
        "error": run.error_message,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _deterministic_execute(case: EvaluationCase) -> dict[str, Any]:
    agents = json.loads(case.expected_agent_json)
    tools = json.loads(case.expected_tools_json)
    citations = json.loads(case.expected_citations_json)
    checks = json.loads(case.auto_checks_json)
    return {
        "classification": case.category,
        "agents": agents,
        "tools": tools,
        "citations": citations,
        "refused": bool(case.expected_refusal),
        "clarification_triggered": bool(checks.get("expect_clarification")),
        "plan_complete": bool(agents or case.expected_refusal or checks.get("expect_clarification")),
        "file_relation_identified": case.category in {"multi_table", "cross_source"},
        "data_checks_passed": case.category
        in {"table_analysis", "multi_table", "cross_source", "report_integrity"},
        "report_sections_complete": bool(checks.get("require_report_sections")),
        "numeric_consistency": bool(checks.get("require_numeric_consistency")),
        "quality_review_blocked": False,
    }


def _score_case(case: EvaluationCase, actual: dict[str, Any]) -> dict[str, bool]:
    expected_agents = json.loads(case.expected_agent_json)
    expected_tools = json.loads(case.expected_tools_json)
    expected_citations = json.loads(case.expected_citations_json)
    rules = json.loads(case.auto_checks_json)
    return {
        "classification_correct": actual["classification"] == case.category,
        "clarification_correct": actual["clarification_triggered"]
        == bool(rules.get("expect_clarification")),
        "plan_complete": actual["plan_complete"],
        "tool_routing_correct": actual["tools"] == expected_tools,
        "tool_calls_successful": all(tool in actual["tools"] for tool in expected_tools),
        "file_relation_correct": (
            actual["file_relation_identified"]
            if case.category in {"multi_table", "cross_source"}
            else True
        ),
        "data_conclusion_passed": (
            actual["data_checks_passed"]
            if rules.get("require_numeric_consistency")
            else True
        ),
        "citation_hit": (
            all(item in actual["citations"] for item in expected_citations)
            if expected_citations
            else True
        ),
        "refusal_correct": actual["refused"] == bool(case.expected_refusal),
        "report_sections_complete": (
            actual["report_sections_complete"]
            if rules.get("require_report_sections")
            else True
        ),
        "numeric_consistency": (
            actual["numeric_consistency"]
            if rules.get("require_numeric_consistency")
            else True
        ),
        "agents_correct": actual["agents"] == expected_agents,
    }


def _aggregate_metrics(
    cases: list[EvaluationCase], results: list[EvaluationResult]
) -> dict[str, Any]:
    parsed = [json.loads(item.metrics_json) for item in results]
    durations = sorted(item.duration_ms for item in results)

    def rate(key: str) -> float:
        return round(sum(bool(item.get(key)) for item in parsed) / max(1, len(parsed)), 4)

    return {
        "case_count": len(results),
        "task_classification_accuracy": rate("classification_correct"),
        "clarification_trigger_accuracy": rate("clarification_correct"),
        "plan_step_completeness": rate("plan_complete"),
        "tool_routing_accuracy": rate("tool_routing_correct"),
        "tool_call_success_rate": rate("tool_calls_successful"),
        "file_relation_accuracy": rate("file_relation_correct"),
        "data_conclusion_check_rate": rate("data_conclusion_passed"),
        "rag_citation_hit_rate": rate("citation_hit"),
        "refusal_accuracy": rate("refusal_correct"),
        "report_section_completeness": rate("report_sections_complete"),
        "numeric_consistency_rate": rate("numeric_consistency"),
        "quality_review_block_rate": round(
            sum(
                json.loads(item.actual_result_json).get("quality_review_blocked", False)
                for item in results
            )
            / max(1, len(results)),
            4,
        ),
        "task_success_rate": round(
            sum(item.status == "passed" for item in results) / max(1, len(results)), 4
        ),
        "average_response_ms": round(mean(durations), 2) if durations else 0,
        "p95_response_ms": durations[max(0, int(len(durations) * 0.95 + 0.999) - 1)]
        if durations
        else 0,
        "average_model_calls": round(mean(item.model_calls for item in results), 2),
        "average_tool_calls": round(mean(item.tool_calls for item in results), 2),
    }
