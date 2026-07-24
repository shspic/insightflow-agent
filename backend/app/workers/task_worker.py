import json
import signal
import socket
import threading
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.specialists import get_specialist_agent
from app.agents.tool_registry import ToolContext, ToolExecutionError
from app.agents.v2_state import AgentStateV2, load_agent_state
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.agent_run import AgentRun
from app.models.operations import WorkerStatus
from app.models.report import Report
from app.models.task import Task
from app.models.task_step import TaskStep
from app.services.security_service import sanitize_details
from app.services.prompt_version_service import get_active_prompt
from app.services.quota_service import increment_usage
from app.services.task_event_service import append_task_event
from app.services.task_queue_service import (
    claim_next_task,
    heartbeat_task,
    release_task_lease,
)
from app.services.task_state_machine import (
    set_task_failure,
    set_task_progress,
    transition_task,
)
from app.services.workspace_service import safe_public_text


class TaskWorker:
    def __init__(self, worker_id: str | None = None) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            with SessionLocal() as db:
                _touch_worker(db, self.worker_id, status="idle")
                task = claim_next_task(db, worker_id=self.worker_id)
                if task is not None:
                    _touch_worker(db, self.worker_id, status="busy", task=task)
                    self.execute_claimed_task(db, task)
                    continue
            self._stop_event.wait(max(0.05, settings.worker_poll_interval_seconds))

    def run_once(self, db: Session | None = None) -> bool:
        owns_session = db is None
        current_db = db or SessionLocal()
        try:
            _touch_worker(current_db, self.worker_id, status="idle")
            task = claim_next_task(current_db, worker_id=self.worker_id)
            if task is None:
                return False
            _touch_worker(current_db, self.worker_id, status="busy", task=task)
            self.execute_claimed_task(current_db, task, background_heartbeat=owns_session)
            return True
        finally:
            if owns_session:
                current_db.close()

    def execute_claimed_task(
        self,
        db: Session,
        task: Task,
        *,
        background_heartbeat: bool = True,
    ) -> None:
        heartbeat = _LeaseHeartbeat(task.id, self.worker_id)
        if background_heartbeat:
            heartbeat.start()
        try:
            self._execute(db, task)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            db.rollback()
            task = db.get(Task, task.id)
            if task and task.status not in {"completed", "completed_with_warnings", "failed", "cancelled"}:
                set_task_failure(task, error_code="WORKER_EXECUTION_ERROR", error_message=str(exc))
                transition_task(
                    db,
                    task,
                    "failed",
                    message="Worker 执行失败，任务已记录为 failed。",
                    event_type="task_failed",
                )
                release_task_lease(db, task)
                increment_usage(db, task.owner_user_id, tasks_failed=1)
                _touch_worker(db, self.worker_id, status="idle", failed_delta=1)
                db.commit()
        finally:
            heartbeat.stop()

    def _execute(self, db: Session, task: Task) -> None:
        if task.status != "running" or task.worker_id != self.worker_id:
            return
        if not task.agent_state_json:
            raise ValueError("任务缺少可恢复的 AgentState")
        state = load_agent_state(task.agent_state_json)
        while True:
            db.refresh(task)
            if task.cancellation_requested_at is not None:
                self._cancel(db, task)
                return
            steps = list(
                db.scalars(
                    select(TaskStep)
                    .where(TaskStep.task_id == task.id)
                    .order_by(TaskStep.step_order.asc())
                ).all()
            )
            step = next(
                (item for item in steps if item.status in {"queued", "pending", "retrying"}),
                None,
            )
            if step is None:
                self._complete(db, task, state, steps)
                return
            if not self._dependencies_complete(step, steps):
                self._fail_dependency(db, task, step)
                return
            if step.agent_type == "quality_review_agent" and task.status == "running":
                transition_task(
                    db,
                    task,
                    "reviewing",
                    message="进入 Quality Review 阶段。",
                    progress_percent=task.progress_percent,
                )
            output = self._execute_step(db, task, step, state, len(steps))
            if output is None:
                return
            if step.agent_type == "quality_review_agent":
                review_status = output.get("status")
                if (
                    review_status == "retry_required"
                    and task.retry_count < max(0, settings.agent_max_review_retries)
                    and output.get("retry_step_ids")
                ):
                    self._schedule_review_retry(
                        db,
                        task,
                        state,
                        steps,
                        output["retry_step_ids"],
                    )
                    continue
                if review_status == "failed":
                    set_task_failure(
                        task,
                        error_code="QUALITY_REVIEW_FAILED",
                        error_message="Quality Review 未通过。",
                    )
                    transition_task(
                        db,
                        task,
                        "failed",
                        message="Quality Review 未通过，任务失败。",
                        event_type="task_failed",
                    )
                    release_task_lease(db, task)
                    db.commit()
                    return

    def _execute_step(
        self,
        db: Session,
        task: Task,
        step: TaskStep,
        state: AgentStateV2,
        total_steps: int,
    ) -> dict[str, Any] | None:
        if task.cancellation_requested_at is not None:
            self._cancel(db, task)
            return None
        step.status = "running"
        step.started_at = datetime.utcnow()
        step.failed_at = None
        step.error_code = None
        step.error_message = None
        task.current_step_id = step.id
        state.current_step = {
            "step_id": step.id,
            "step_key": step.step_key,
            "agent_type": step.agent_type,
            "tool_name": step.tool_name,
        }
        append_task_event(
            db,
            task_id=task.id,
            event_type="agent_started",
            message=f"{step.agent_type} 开始执行：{step.title}",
            status=task.status,
            progress_percent=task.progress_percent,
            step_id=step.id,
            agent_type=step.agent_type,
        )
        prompt_name = (
            "quality_review"
            if step.agent_type == "quality_review_agent"
            else step.agent_type
        )
        prompt = get_active_prompt(db, prompt_name)
        run = AgentRun(
            task_id=task.id,
            step_id=step.id,
            agent_type=step.agent_type,
            run_number=step.retry_count + 1,
            provider=(
                settings.llm_provider
                if task.use_deepseek and step.agent_type == "quality_review_agent"
                else "deterministic"
            ),
            model_name=(
                settings.llm_model
                if task.use_deepseek and step.agent_type == "quality_review_agent"
                else None
            ),
            prompt_name=prompt.prompt_name,
            prompt_version=prompt.version,
            prompt_version_id=prompt.id,
            input_summary_json=json.dumps(
                {
                    "selected_file_count": len(state.selected_file_ids),
                    "step_key": step.step_key,
                },
                ensure_ascii=False,
            ),
            status="running",
            fallback_used=0,
        )
        db.add(run)
        db.commit()
        started = time.monotonic()
        try:
            agent = get_specialist_agent(step.agent_type)
            output = agent.execute(
                ToolContext(
                    db=db,
                    task=task,
                    step=step,
                    state=state,
                    agent_run_id=run.id,
                ),
                step,
            )
            if task.cancellation_requested_at is not None:
                self._cancel(db, task)
                return None
            self._apply_output(state, step, output)
            if step.agent_type == "quality_review_agent" and state.report_id is not None:
                report = db.get(Report, state.report_id)
                if report is not None and report.task_id == task.id:
                    review_status = str(output.get("status") or "failed")
                    report.quality_status = review_status
                    report.quality_summary_json = json.dumps(
                        _safe_output(output), ensure_ascii=False, default=str
                    )
                    report.warnings_json = json.dumps(
                        state.warnings, ensure_ascii=False, default=str
                    )
                    report.status = (
                        "failed"
                        if review_status == "failed"
                        else (
                            "ready_with_warnings"
                            if review_status in {"passed_with_warnings", "retry_required"}
                            or state.warnings
                            else "ready"
                        )
                    )
            step.output_json = json.dumps(
                _safe_output(output),
                ensure_ascii=False,
                default=str,
            )
            step.status = "completed"
            step.progress_percent = 100
            step.completed_at = datetime.utcnow()
            if step.step_key not in state.completed_steps:
                state.completed_steps.append(step.step_key)
            state.failed_steps = [key for key in state.failed_steps if key != step.step_key]
            state.current_step = None
            run.status = "completed"
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.output_summary_json = json.dumps(
                _agent_output_summary(output),
                ensure_ascii=False,
                default=str,
            )
            run.tool_calls_json = json.dumps([step.tool_name], ensure_ascii=False)
            model_review = output.get("model_review") or {}
            if model_review.get("token_usage"):
                run.token_usage_json = json.dumps(
                    model_review["token_usage"],
                    ensure_ascii=False,
                    default=str,
                )
            run.fallback_used = int(
                bool(model_review.get("fallback_used", False))
            )
            run.completed_at = datetime.utcnow()
            progress = min(
                95,
                5
                + int(
                    sum(
                        item.status in {"completed", "skipped"}
                        for item in db.scalars(
                            select(TaskStep).where(TaskStep.task_id == task.id)
                        ).all()
                    )
                    / max(1, total_steps)
                    * 90
                ),
            )
            task.agent_state_json = state.model_dump_json()
            append_task_event(
                db,
                task_id=task.id,
                event_type="agent_completed",
                message=f"{step.agent_type} 已完成：{step.title}",
                status=task.status,
                progress_percent=progress,
                step_id=step.id,
                agent_type=step.agent_type,
                payload={"step_key": step.step_key, "output_status": output.get("status")},
            )
            task.progress_percent = progress
            task.last_heartbeat_at = datetime.utcnow()
            db.commit()
            heartbeat_task(db, task_id=task.id, worker_id=self.worker_id)
            return output
        except Exception as exc:
            db.rollback()
            task = db.get(Task, task.id)
            step = db.get(TaskStep, step.id)
            run = db.get(AgentRun, run.id)
            message = exc.message if isinstance(exc, ToolExecutionError) else str(exc)
            code = exc.code if isinstance(exc, ToolExecutionError) else "AGENT_STEP_FAILED"
            step.status = "failed"
            step.failed_at = datetime.utcnow()
            step.error_code = code
            step.error_message = safe_public_text(message)
            run.status = "failed"
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.error_code = code
            run.error_message = safe_public_text(message)
            run.completed_at = datetime.utcnow()
            if step.step_key not in state.failed_steps:
                state.failed_steps.append(step.step_key)
            state.current_step = None
            task.agent_state_json = state.model_dump_json()
            set_task_failure(task, error_code=code, error_message=message)
            append_task_event(
                db,
                task_id=task.id,
                event_type="agent_failed",
                message=f"{step.agent_type} 执行失败：{safe_public_text(message)}",
                status=task.status,
                progress_percent=task.progress_percent,
                step_id=step.id,
                agent_type=step.agent_type,
                payload={"error_code": code},
            )
            transition_task(
                db,
                task,
                "failed",
                message="任务因步骤失败进入 failed，可从失败步骤局部重试。",
                event_type="task_failed",
            )
            release_task_lease(db, task)
            increment_usage(db, task.owner_user_id, tasks_failed=1)
            _touch_worker(db, self.worker_id, status="idle", failed_delta=1)
            db.commit()
            return None

    def _schedule_review_retry(
        self,
        db: Session,
        task: Task,
        state: AgentStateV2,
        steps: list[TaskStep],
        retry_step_ids: list[int],
    ) -> None:
        initial_keys = {item.step_key for item in steps if item.id in retry_step_ids}
        selected_keys = set(initial_keys)
        changed = True
        while changed:
            changed = False
            for item in steps:
                dependencies = _json_list(item.depends_on_json)
                if item.step_key not in selected_keys and selected_keys.intersection(dependencies):
                    selected_keys.add(item.step_key)
                    changed = True
        targets = [item for item in steps if item.step_key in selected_keys]
        if not targets:
            state.warnings.append("Quality Review 请求了无法定位的重试步骤。")
            return
        transition_task(
            db,
            task,
            "retrying",
            message="Quality Review 触发一次受限局部重试。",
            event_type="quality_retry_scheduled",
            payload={"step_ids": [item.id for item in targets]},
        )
        for item in targets:
            item.status = "queued"
            item.progress_percent = 0
            item.retry_count += 1
            item.output_json = None
            item.started_at = None
            item.completed_at = None
            item.failed_at = None
            item.error_code = None
            item.error_message = None
        state.completed_steps = [
            key for key in state.completed_steps if key not in selected_keys
        ]
        state.failed_steps = [key for key in state.failed_steps if key not in selected_keys]
        state.retry_count += 1
        task.retry_count += 1
        task.agent_state_json = state.model_dump_json()
        transition_task(
            db,
            task,
            "running",
            message="局部重试开始，复用未受影响的上游步骤。",
        )
        db.commit()

    def _complete(
        self,
        db: Session,
        task: Task,
        state: AgentStateV2,
        steps: list[TaskStep],
    ) -> None:
        review_status = _latest_review_status(steps)
        state.final_result = {
            "summary": _build_summary(state),
            "data_findings": state.analysis_findings,
            "document_evidence": state.document_evidence,
            "chart_assets": state.chart_assets,
            "warnings": state.warnings,
            "review_findings": state.review_findings,
            "report_id": state.report_id,
        }
        task.final_answer = state.final_result["summary"]
        task.result_summary = json.dumps(
            {
                "summary": state.final_result["summary"],
                "finding_count": len(state.analysis_findings),
                "evidence_count": len(state.document_evidence),
                "chart_count": len(
                    [item for item in state.chart_assets if not item.get("skipped")]
                ),
                "warnings": state.warnings,
                "review_status": review_status,
            },
            ensure_ascii=False,
        )
        task.agent_state_json = state.model_dump_json()
        target = (
            "completed_with_warnings"
            if review_status in {"passed_with_warnings", "retry_required"} or state.warnings
            else "completed"
        )
        transition_task(
            db,
            task,
            target,
            message=(
                "任务已完成，但存在需要人工关注的警告。"
                if target == "completed_with_warnings"
                else "任务已完成并通过质量审核。"
            ),
            progress_percent=100,
            event_type="task_completed",
        )
        task.current_step_id = None
        release_task_lease(db, task)
        duration_ms = 0
        if task.started_at:
            duration_ms = max(0, int((datetime.utcnow() - task.started_at).total_seconds() * 1000))
        increment_usage(
            db,
            task.owner_user_id,
            tasks_succeeded=1,
            task_duration_ms=duration_ms,
        )
        _touch_worker(db, self.worker_id, status="idle", completed_delta=1)
        db.commit()

    def _cancel(self, db: Session, task: Task) -> None:
        for step in db.scalars(
            select(TaskStep).where(
                TaskStep.task_id == task.id,
                TaskStep.status.in_(["pending", "queued", "retrying"]),
            )
        ).all():
            step.status = "cancelled"
        if task.status not in {"cancelled", "completed", "completed_with_warnings", "failed"}:
            transition_task(
                db,
                task,
                "cancelled",
                message="Worker 已在步骤边界响应取消请求。",
                event_type="task_cancelled",
            )
        task.current_step_id = None
        release_task_lease(db, task)
        db.commit()

    @staticmethod
    def _dependencies_complete(step: TaskStep, steps: list[TaskStep]) -> bool:
        by_key = {item.step_key: item for item in steps}
        return all(
            dependency in by_key
            and by_key[dependency].status in {"completed", "skipped"}
            for dependency in _json_list(step.depends_on_json)
        )

    @staticmethod
    def _fail_dependency(db: Session, task: Task, step: TaskStep) -> None:
        step.status = "failed"
        step.error_code = "DEPENDENCY_NOT_COMPLETED"
        step.error_message = "步骤依赖未完成"
        step.failed_at = datetime.utcnow()
        set_task_failure(
            task,
            error_code="DEPENDENCY_NOT_COMPLETED",
            error_message="计划步骤依赖未完成",
        )
        transition_task(
            db,
            task,
            "failed",
            message="任务因计划依赖未完成而失败。",
            event_type="task_failed",
        )
        release_task_lease(db, task)
        db.commit()

    @staticmethod
    def _apply_output(
        state: AgentStateV2,
        step: TaskStep,
        output: dict[str, Any],
    ) -> None:
        if step.agent_type == "file_understanding_agent":
            state.workspace_context = output.get("workspace_context") or {}
            state.confirmed_relations = output.get("confirmed_relations") or []
            for item in output.get("unready_files") or []:
                warning = f"文件 {item.get('filename')} 的 Profile 状态为 {item.get('profile_status')}。"
                if warning not in state.warnings:
                    state.warnings.append(warning)
        elif step.agent_type == "data_analysis_agent":
            state.analysis_findings = output.get("findings") or []
            state.chart_assets = output.get("chart_assets") or []
            state.warnings.extend(
                item for item in output.get("warnings") or [] if item not in state.warnings
            )
        elif step.agent_type == "document_research_agent":
            state.document_evidence = output.get("evidence") or []
            if output.get("status") == "evidence_not_found":
                state.warnings.append("所选文档未检索到与用户目标直接相关的证据。")
        elif step.agent_type == "report_agent":
            state.report_sections = output.get("sections") or []
            state.report_id = output.get("report_id")
        elif step.agent_type == "quality_review_agent":
            state.review_findings = output.get("issues") or []


def _touch_worker(
    db: Session,
    worker_id: str,
    *,
    status: str,
    task: Task | None = None,
    completed_delta: int = 0,
    failed_delta: int = 0,
) -> WorkerStatus:
    now = datetime.utcnow()
    record = db.scalar(
        select(WorkerStatus).where(WorkerStatus.worker_id == worker_id)
    )
    if record is None:
        record = WorkerStatus(
            worker_id=worker_id,
            status=status,
            last_heartbeat_at=now,
            current_task_id=task.id if task else None,
            lease_expires_at=task.lease_expires_at if task else None,
            started_at=now,
        )
        db.add(record)
    else:
        record.status = status
        record.last_heartbeat_at = now
        record.current_task_id = task.id if task else None
        record.lease_expires_at = task.lease_expires_at if task else None
        record.completed_tasks += completed_delta
        record.failed_tasks += failed_delta
    db.commit()
    return record


class _LeaseHeartbeat:
    def __init__(self, task_id: int, worker_id: str) -> None:
        self.task_id = task_id
        self.worker_id = worker_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        interval = max(1, settings.worker_heartbeat_seconds)
        while not self._stop.wait(interval):
            try:
                with SessionLocal() as db:
                    if not heartbeat_task(
                        db,
                        task_id=self.task_id,
                        worker_id=self.worker_id,
                    ):
                        return
                    _touch_worker(db, self.worker_id, status="busy", task=db.get(Task, self.task_id))
            except Exception:
                continue


def _safe_output(output: dict[str, Any]) -> dict[str, Any]:
    value = sanitize_details(output)
    value.pop("content", None)
    return value


def _agent_output_summary(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": output.get("status"),
        "finding_count": len(output.get("findings") or []),
        "evidence_count": len(output.get("evidence") or []),
        "chart_count": len(output.get("chart_assets") or []),
        "issue_count": len(output.get("issues") or []),
        "report_id": output.get("report_id"),
    }


def _latest_review_status(steps: list[TaskStep]) -> str | None:
    review = next(
        (item for item in reversed(steps) if item.agent_type == "quality_review_agent"),
        None,
    )
    if review is None or not review.output_json:
        return None
    try:
        return json.loads(review.output_json).get("status")
    except json.JSONDecodeError:
        return None


def _build_summary(state: AgentStateV2) -> str:
    return (
        f"已完成 {len(state.selected_file_ids)} 个文件的综合分析，"
        f"形成 {len(state.analysis_findings)} 组数据结论、"
        f"{len(state.document_evidence)} 条文档证据和"
        f"{len([item for item in state.chart_assets if not item.get('skipped')])} 个图表。"
    )


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def main() -> None:
    worker = TaskWorker()

    def stop_worker(*_: object) -> None:
        worker.stop()

    signal.signal(signal.SIGINT, stop_worker)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_worker)
    print(f"InsightFlow Worker 已启动：{worker.worker_id}")
    worker.run_forever()
    print("InsightFlow Worker 已安全退出。")


if __name__ == "__main__":
    main()
