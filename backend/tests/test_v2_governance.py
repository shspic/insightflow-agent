import hashlib
import json
import sqlite3
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.evaluation.dataset import CATEGORY_COUNTS, load_v2_core_dataset
from app.evaluation.runner import run_evaluation
from app.maintenance import backup as backup_service
from app.maintenance.restore import restore_database
from app.maintenance.cleanup import run_cleanup
from app.models.auth_session import AuthSession
from app.models.evaluation import EvaluationCase, EvaluationResult
from app.models.prompt_version import PromptVersion
from app.models.task import Task
from app.models.task_plan import TaskPlan
from app.models.task_step import TaskStep
from app.models.usage import QuotaOverride, UsageCounter
from app.models.user import User
from app.services.prompt_version_service import activate_prompt, get_active_prompt
from app.services.quota_service import (
    QuotaExceeded,
    check_task_creation,
    set_quota_override,
    usage_snapshot,
)
from app.services.task_queue_service import requeue_task_for_reanalysis
from app.schemas.report_delivery import FeedbackCreate


def _user(db_session, username="quota-user", role="user"):
    user = User(username=username, password_hash="x", role=role, status="active")
    db_session.add(user)
    db_session.flush()
    return user


def test_quota_default_override_and_expiry(db_session):
    user = _user(db_session)
    counter = UsageCounter(
        user_id=user.id,
        usage_date=date.today(),
        tasks_created=20,
    )
    db_session.add(counter)
    db_session.flush()
    with pytest.raises(QuotaExceeded) as captured:
        check_task_creation(db_session, user)
    assert captured.value.quota_key == "daily_tasks"

    active = set_quota_override(
        db_session,
        target_user_id=user.id,
        quota_key="daily_tasks",
        limit_value=25,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        note="测试覆盖",
        admin_user_id=user.id,
    )
    check_task_creation(db_session, user)
    active.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.flush()
    with pytest.raises(QuotaExceeded):
        check_task_creation(db_session, user)
    snapshot = usage_snapshot(db_session, user)
    assert snapshot["usage"]["daily_tasks"] == 20
    assert snapshot["reset_at"]


def test_prompt_single_active_and_sensitive_filter(db_session):
    admin = _user(db_session, "prompt-admin", "admin")
    first = get_active_prompt(db_session, "planning")
    template = "安全的结构化计划版本，不允许注册任意工具。"
    second = PromptVersion(
        prompt_name="planning",
        version="2.05.2",
        status="draft",
        purpose="测试安全切换",
        template_text=template,
        input_schema_json="{}",
        output_schema_json="{}",
        content_hash=hashlib.sha256(template.encode("utf-8")).hexdigest(),
    )
    db_session.add(second)
    db_session.flush()
    activate_prompt(db_session, second.id, admin.id)
    assert second.status == "active"
    assert first.status == "retired"
    assert db_session.scalar(
        select(func.count(PromptVersion.id)).where(
            PromptVersion.prompt_name == "planning",
            PromptVersion.status == "active",
        )
    ) == 1

    unsafe_text = "api_key=sk-this-is-a-real-looking-secret"
    unsafe = PromptVersion(
        prompt_name="planning",
        version="2.05.3",
        status="draft",
        purpose="不安全版本",
        template_text=unsafe_text,
        input_schema_json="{}",
        output_schema_json="{}",
        content_hash=hashlib.sha256(unsafe_text.encode("utf-8")).hexdigest(),
    )
    db_session.add(unsafe)
    db_session.flush()
    with pytest.raises(ValueError):
        activate_prompt(db_session, unsafe.id, admin.id)


def test_deterministic_evaluation_has_85_persisted_cases_and_no_model_calls(db_session):
    dataset = load_v2_core_dataset(db_session)
    assert sum(CATEGORY_COUNTS.values()) == 85
    assert db_session.scalar(
        select(func.count(EvaluationCase.id)).where(EvaluationCase.dataset_id == dataset.id)
    ) == 85
    run = run_evaluation(
        db_session,
        dataset_name="v2-core",
        mode="deterministic",
    )
    results = db_session.scalars(
        select(EvaluationResult).where(EvaluationResult.run_id == run.id)
    ).all()
    metrics = json.loads(run.metrics_json)
    assert run.status == "completed"
    assert len(results) == 85
    assert all(item.model_calls == 0 for item in results)
    assert metrics["case_count"] == 85
    assert metrics["task_success_rate"] == 1.0
    resource_root = Path(__file__).parents[1] / "app" / "evaluation"
    ocr_case = db_session.scalar(
        select(EvaluationCase).where(EvaluationCase.category == "ocr")
    )
    for resource in json.loads(ocr_case.resource_refs_json):
        assert (resource_root / resource).is_file()


def test_feedback_rejects_execution_controls_and_reanalysis_requeues_controlled_steps(
    db_session,
):
    user = _user(db_session, "reanalysis-user")
    with pytest.raises(ValueError):
        FeedbackCreate.model_validate(
            {
                "feedback_type": "correction",
                "correction": {"statement": "tool_name=arbitrary_shell"},
            }
        )

    task = Task(
        owner_user_id=user.id,
        user_input="重新分析合成资料",
        status="completed",
        file_ids_json="[]",
        agent_state_json=json.dumps(
            {
                "completed_steps": ["understand", "analyze", "report", "review"],
                "failed_steps": [],
                "analysis_findings": [{"value": 1}],
                "document_evidence": [],
                "chart_assets": [],
                "report_sections": ["摘要"],
                "review_findings": [],
                "final_result": {"summary": "旧结果"},
                "report_id": 1,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(task)
    db_session.flush()
    plan = TaskPlan(
        task_id=task.id,
        version=1,
        status="confirmed",
        goal="重新分析",
        selected_file_ids_json="[]",
        assumptions_json="[]",
        steps_json="[]",
        estimated_model_calls=0,
        estimated_tool_calls=3,
    )
    db_session.add(plan)
    db_session.flush()
    task.current_plan_id = plan.id
    steps = [
        TaskStep(
            task_id=task.id,
            plan_id=plan.id,
            step_key=key,
            step_order=index,
            agent_type=agent,
            tool_name=tool,
            title=key,
            status="completed",
            progress_percent=100,
            depends_on_json="[]",
        )
        for index, (key, agent, tool) in enumerate(
            [
                ("understand", "file_understanding_agent", "workspace_context_lookup"),
                ("analyze", "data_analysis_agent", "preset_multi_table_analysis"),
                ("report", "report_agent", "structured_markdown_report"),
                ("review", "quality_review_agent", "deterministic_quality_review"),
            ],
            start=1,
        )
    ]
    db_session.add_all(steps)
    db_session.flush()
    requeue_task_for_reanalysis(db_session, task)
    assert task.status == "queued"
    assert steps[0].status == "completed"
    assert all(item.status == "queued" for item in steps[1:])
    state = json.loads(task.agent_state_json)
    assert state["analysis_findings"] == []
    assert state["report_id"] is None


def test_cleanup_dry_run_then_apply_deletes_only_expired_session(db_session):
    user = _user(db_session, "cleanup-user")
    expired = AuthSession(
        user_id=user.id,
        token_hash="expired",
        expires_at=datetime.utcnow() - timedelta(days=60),
    )
    active = AuthSession(
        user_id=user.id,
        token_hash="active",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    db_session.add_all([expired, active])
    db_session.commit()
    dry = run_cleanup(
        db_session,
        dry_run=True,
        now=datetime.utcnow(),
        execution_source="test",
    )
    assert dry.deleted_count == 0
    assert db_session.get(AuthSession, expired.id) is not None
    applied = run_cleanup(
        db_session,
        dry_run=False,
        now=datetime.utcnow(),
        execution_source="test",
    )
    assert applied.deleted_count >= 1
    assert db_session.get(AuthSession, expired.id) is None
    assert db_session.get(AuthSession, active.id) is not None


def test_backup_manifest_checksum_and_restore_protection(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('synthetic')")
    monkeypatch.setattr(backup_service, "_sqlite_database_path", lambda: source)
    result = backup_service.create_backup(tmp_path / "backups")
    backup_dir = Path(result["backup_dir"])
    assert backup_service.verify_backup(backup_dir)["status"] == "verified"
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert ".env" in manifest["excluded"]
    assert manifest["files"]["database.sqlite3"]["sha256"]
    with zipfile.ZipFile(backup_dir / "storage.zip") as archive:
        assert all(not name.endswith(".env") for name in archive.namelist())
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"do-not-overwrite")
    with pytest.raises(RuntimeError):
        restore_database(backup_dir, existing)
    restored = tmp_path / "restored.db"
    assert restore_database(backup_dir, restored)["status"] == "restored"
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "synthetic"
