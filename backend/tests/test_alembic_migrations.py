import os
from pathlib import Path
import subprocess
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
BASELINE_REVISION = "20260723_0001"
V2_02_REVISION = "20260723_0003"
PREVIOUS_REVISION = V2_02_REVISION
V2_03_REVISION = "20260723_0004"
V2_04_REVISION = "20260724_0005"
V2_05_REVISION = "20260724_0006"
HEAD_REVISION = "20260808_0012"
V2_TABLES = {
    "users",
    "auth_sessions",
    "invite_codes",
    "password_reset_requests",
    "workspaces",
    "workspace_files",
    "audit_logs",
    "auth_rate_limits",
    "file_profiles",
    "file_relations",
    "file_processing_runs",
    "task_clarifications",
    "task_plans",
    "task_steps",
    "task_events",
    "agent_runs",
    "reports",
    "report_assets",
    "user_feedback",
    "prompt_versions",
    "usage_counters",
    "quota_overrides",
    "model_usage_records",
    "evaluation_datasets",
    "evaluation_cases",
    "evaluation_runs",
    "evaluation_results",
    "cleanup_runs",
    "worker_statuses",
}
V3_2A_TABLES = {
    "review_runs",
    "evidences",
    "review_findings",
    "review_actions",
    "review_briefs",
}
V3_3B_TABLES = {"review_reports", "review_report_assets"}
V4C2_TABLES = {"review_verification_runs", "review_tool_calls"}
V4C3_TABLES = {"review_candidate_decisions"}


def test_alembic_upgrade_head_creates_v2_schema(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "fresh.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)

    command.upgrade(alembic_config, "head")

    engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(engine)
    assert V2_TABLES.issubset(inspector.get_table_names())
    assert V3_2A_TABLES.issubset(inspector.get_table_names())
    assert V3_3B_TABLES.issubset(inspector.get_table_names())
    assert V4C2_TABLES.issubset(inspector.get_table_names())
    assert V4C3_TABLES.issubset(inspector.get_table_names())
    assert {
        "workspace_id",
        "owner_user_id",
        "review_run_id",
        "version",
        "status",
        "review_state_hash",
        "review_snapshot_json",
        "quality_gate_json",
        "warning_count",
        "finding_count",
        "generator_name",
        "generator_version",
    }.issubset(_column_names(inspector, "review_reports"))
    assert {
        "review_report_id",
        "workspace_id",
        "owner_user_id",
        "asset_type",
        "file_name",
        "storage_path",
        "mime_type",
        "size_bytes",
        "content_hash",
    }.issubset(_column_names(inspector, "review_report_assets"))
    assert {"owner_user_id"}.issubset(_column_names(inspector, "files"))
    assert {"mime_type", "size_bytes"}.issubset(_column_names(inspector, "files"))
    assert "csrf_token_hash" in _column_names(inspector, "auth_sessions")
    assert {
        "source_type",
        "section_path",
        "char_start",
        "char_end",
        "chunk_hash",
        "parser_version",
    }.issubset(_column_names(inspector, "file_chunks"))
    assert {
        "owner_user_id",
        "workspace_id",
        "progress_percent",
        "worker_id",
        "lease_expires_at",
        "agent_state_json",
    }.issubset(_column_names(inspector, "tasks"))
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    engine.dispose()


def test_existing_baseline_data_survives_v2_upgrade(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "legacy.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, BASELINE_REVISION)

    engine = create_engine(_sqlite_url(database_path))
    now = "2026-07-23 00:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO files (
                    id, filename, file_type, file_path, status, summary, schema_json, created_at, updated_at
                ) VALUES (
                    1, 'legacy.csv', 'csv', 'storage/uploads/legacy.csv', 'pending', NULL, NULL, :now, :now
                )
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO tasks (
                    id, user_input, task_type, status, file_ids_json, final_answer, report_path,
                    created_at, updated_at
                ) VALUES (
                    1, '旧任务', NULL, 'pending', '[1]', NULL, NULL, :now, :now
                )
                """
            ),
            {"now": now},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")

    upgraded_engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(upgraded_engine)
    with upgraded_engine.connect() as connection:
        assert connection.execute(text("SELECT filename FROM files WHERE id = 1")).scalar_one() == "legacy.csv"
        assert connection.execute(text("SELECT user_input FROM tasks WHERE id = 1")).scalar_one() == "旧任务"
    assert "owner_user_id" in _column_names(inspector, "files")
    assert {"owner_user_id", "workspace_id"}.issubset(_column_names(inspector, "tasks"))
    upgraded_engine.dispose()


def test_v2_migration_can_downgrade_to_baseline(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "rollback.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, BASELINE_REVISION)

    engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(engine)
    assert V2_TABLES.isdisjoint(inspector.get_table_names())
    assert "owner_user_id" not in _column_names(inspector, "files")
    assert "workspace_id" not in _column_names(inspector, "tasks")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == BASELINE_REVISION
    engine.dispose()


def test_v2_02_migration_can_downgrade_and_upgrade_again(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "v2-02-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, "20260723_0002")
    engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(engine)
    assert "auth_rate_limits" not in inspector.get_table_names()
    assert "csrf_token_hash" not in _column_names(inspector, "auth_sessions")
    assert "mime_type" not in _column_names(inspector, "files")
    engine.dispose()

    command.upgrade(alembic_config, "head")
    upgraded_engine = create_engine(_sqlite_url(database_path))
    upgraded_inspector = inspect(upgraded_engine)
    assert "auth_rate_limits" in upgraded_inspector.get_table_names()
    assert "csrf_token_hash" in _column_names(upgraded_inspector, "auth_sessions")
    with upgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    upgraded_engine.dispose()


def test_v2_03_migration_can_downgrade_to_v2_02_and_upgrade_again(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "v2-03-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, V2_02_REVISION)
    engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(engine)
    assert "file_profiles" not in inspector.get_table_names()
    assert "file_relations" not in inspector.get_table_names()
    assert "file_processing_runs" not in inspector.get_table_names()
    assert "source_type" not in _column_names(inspector, "file_chunks")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == V2_02_REVISION
    engine.dispose()

    command.upgrade(alembic_config, "head")
    upgraded_engine = create_engine(_sqlite_url(database_path))
    upgraded_inspector = inspect(upgraded_engine)
    assert {
        "file_profiles",
        "file_relations",
        "file_processing_runs",
    }.issubset(upgraded_inspector.get_table_names())
    assert "source_type" in _column_names(upgraded_inspector, "file_chunks")
    with upgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    upgraded_engine.dispose()


def test_v2_04_migration_can_downgrade_to_v2_03_and_upgrade_again(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "v2-04-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, V2_03_REVISION)
    engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(engine)
    assert "task_plans" not in inspector.get_table_names()
    assert "task_events" not in inspector.get_table_names()
    assert "worker_id" not in _column_names(inspector, "tasks")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == V2_03_REVISION
    engine.dispose()

    command.upgrade(alembic_config, "head")
    upgraded_engine = create_engine(_sqlite_url(database_path))
    upgraded_inspector = inspect(upgraded_engine)
    assert {
        "task_clarifications",
        "task_plans",
        "task_steps",
        "task_events",
        "agent_runs",
    }.issubset(upgraded_inspector.get_table_names())
    assert "worker_id" in _column_names(upgraded_inspector, "tasks")
    with upgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    upgraded_engine.dispose()


def test_v2_05_migration_can_downgrade_to_v2_04_and_upgrade_again(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "v2-05-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, HEAD_REVISION)

    command.downgrade(alembic_config, V2_04_REVISION)
    engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(engine)
    assert "reports" not in inspector.get_table_names()
    assert "prompt_versions" not in inspector.get_table_names()
    assert "prompt_name" not in _column_names(inspector, "agent_runs")
    assert "workspace_type" not in _column_names(inspector, "workspaces")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == V2_04_REVISION
    engine.dispose()

    command.upgrade(alembic_config, HEAD_REVISION)
    upgraded_engine = create_engine(_sqlite_url(database_path))
    upgraded_inspector = inspect(upgraded_engine)
    assert {
        "reports",
        "report_assets",
        "user_feedback",
        "prompt_versions",
        "usage_counters",
        "quota_overrides",
        "model_usage_records",
        "evaluation_datasets",
        "evaluation_cases",
        "evaluation_runs",
        "evaluation_results",
        "cleanup_runs",
        "worker_statuses",
    }.issubset(upgraded_inspector.get_table_names())
    assert {"prompt_name", "prompt_version_id"}.issubset(
        _column_names(upgraded_inspector, "agent_runs")
    )
    assert "workspace_type" in _column_names(upgraded_inspector, "workspaces")
    with upgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        active_count = connection.execute(
            text("SELECT COUNT(*) FROM prompt_versions WHERE status = 'active'")
        ).scalar_one()
    assert revision == HEAD_REVISION
    assert active_count == 7
    upgraded_engine.dispose()


def test_v3_01_workspace_type_migration_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """验证 V3 workspace_type 迁移：旧数据 → general，约束、downgrade/upgrade。"""
    database_path = tmp_path / "v3-01-workspace-type.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)

    # 先升级到 V2-05 head，插入一条旧工作区
    command.upgrade(alembic_config, V2_05_REVISION)
    engine = create_engine(_sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, status, must_change_password, created_at, updated_at) "
                "VALUES (1, 'v3test', 'hash', 'user', 'active', 0, '2026-08-06', '2026-08-06')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, status, created_at, updated_at) "
                "VALUES (1, 1, '旧工作区', 'active', '2026-08-06', '2026-08-06')"
            )
        )
    engine.dispose()

    # 升级到 V3 head
    command.upgrade(alembic_config, HEAD_REVISION)
    upgraded_engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(upgraded_engine)
    assert "workspace_type" in _column_names(inspector, "workspaces")

    with upgraded_engine.connect() as connection:
        # 旧工作区自动迁移为 general
        row = connection.execute(
            text("SELECT workspace_type FROM workspaces WHERE id = 1")
        ).one()
        assert row[0] == "general"

        # workspace_type 非空
        null_count = connection.execute(
            text("SELECT COUNT(*) FROM workspaces WHERE workspace_type IS NULL")
        ).scalar_one()
        assert null_count == 0

    # 非法类型被数据库约束拒绝
    with upgraded_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, status, created_at, updated_at) "
                "VALUES (2, 1, 'test', 'engineering', 'active', '2026-08-06', '2026-08-06')"
            )
        )
    with upgraded_engine.connect() as connection:
        row = connection.execute(
            text("SELECT workspace_type FROM workspaces WHERE id = 2")
        ).one()
        assert row[0] == "engineering"

    import pytest
    with pytest.raises(Exception):
        with upgraded_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, status, created_at, updated_at) "
                    "VALUES (3, 1, 'invalid', 'bad_type', 'active', '2026-08-06', '2026-08-06')"
                )
            )
    upgraded_engine.dispose()

    # downgrade 回去
    command.downgrade(alembic_config, V2_05_REVISION)
    downgraded_engine = create_engine(_sqlite_url(database_path))
    downgraded_inspector = inspect(downgraded_engine)
    assert "workspace_type" not in _column_names(downgraded_inspector, "workspaces")
    with downgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == V2_05_REVISION
    downgraded_engine.dispose()

    # 再次 upgrade 成功
    command.upgrade(alembic_config, HEAD_REVISION)
    reupgraded_engine = create_engine(_sqlite_url(database_path))
    with reupgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    reupgraded_engine.dispose()


def test_init_db_compatibility_entry_uses_alembic(tmp_path: Path) -> None:
    database_path = tmp_path / "init-db.db"
    database_url = _sqlite_url(database_path)
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": database_url,
            "ALEMBIC_DATABASE_URL": database_url,
            "LLM_ENABLED": "false",
            "LLM_API_KEY": "",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.db.init_db"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    engine = create_engine(database_url)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    engine.dispose()


def test_v3_2a_review_models_migration_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """V3 2A 迁移：从 0007 升级 → 降级 → 再升级，四张表 + review_template_key。"""
    database_path = tmp_path / "v3-2a-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)

    # 先升级到 0007
    command.upgrade(alembic_config, "20260806_0007")
    engine = create_engine(_sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, status, must_change_password, created_at, updated_at) "
                "VALUES (1, 'v3test', 'hash', 'user', 'active', 0, '2026-08-06', '2026-08-06')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, status, created_at, updated_at) "
                "VALUES (1, 1, '工程项目', 'engineering', 'active', '2026-08-06', '2026-08-06')"
            )
        )
    engine.dispose()

    # 升级到 head (0008)
    command.upgrade(alembic_config, HEAD_REVISION)
    upgraded_engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(upgraded_engine)

    # 新表存在
    assert V3_2A_TABLES.issubset(inspector.get_table_names())

    # review_template_key 列存在
    assert "review_template_key" in _column_names(inspector, "workspaces")

    # 已有工作区数据完好
    with upgraded_engine.connect() as connection:
        row = connection.execute(
            text("SELECT name, workspace_type, review_template_key FROM workspaces WHERE id = 1")
        ).one()
        assert row[0] == "工程项目"
        assert row[1] == "engineering"
        assert row[2] is None  # 旧数据没有设置模板

    # 设置 engineering 模板
    with upgraded_engine.begin() as connection:
        connection.execute(
            text("UPDATE workspaces SET review_template_key = 'engineering_bid_review_v1' WHERE id = 1")
        )

    # 非法模板值被拒绝
    import pytest
    with pytest.raises(Exception):
        with upgraded_engine.begin() as connection:
            connection.execute(
                text("UPDATE workspaces SET review_template_key = 'bad_template' WHERE id = 1")
            )
    upgraded_engine.dispose()

    # 降级到 0007
    command.downgrade(alembic_config, "20260806_0007")
    downgraded_engine = create_engine(_sqlite_url(database_path))
    downgraded_inspector = inspect(downgraded_engine)
    assert V3_2A_TABLES.isdisjoint(downgraded_inspector.get_table_names())
    assert "review_template_key" not in _column_names(downgraded_inspector, "workspaces")
    with downgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "20260806_0007"
    downgraded_engine.dispose()

    # 再次 upgrade 到 head
    command.upgrade(alembic_config, HEAD_REVISION)
    reupgraded_engine = create_engine(_sqlite_url(database_path))
    with reupgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    reupgraded_engine.dispose()


def test_v3_2a_stage1_data_survives_upgrade(tmp_path: Path, monkeypatch) -> None:
    """从 0007 升级到 0008 后阶段 1 数据完整保留。"""
    database_path = tmp_path / "v3-2a-data-survival.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)

    command.upgrade(alembic_config, "20260806_0007")
    engine = create_engine(_sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, status, must_change_password, created_at, updated_at) "
                "VALUES (1, 'user1', 'hash', 'user', 'active', 0, '2026-08-06', '2026-08-06')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, status, created_at, updated_at) "
                "VALUES (1, 1, '工程', 'engineering', 'active', '2026-08-06', '2026-08-06')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, status, created_at, updated_at) "
                "VALUES (2, 1, '通用', 'general', 'active', '2026-08-06', '2026-08-06')"
            )
        )
    engine.dispose()

    command.upgrade(alembic_config, HEAD_REVISION)
    upgraded_engine = create_engine(_sqlite_url(database_path))
    with upgraded_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, name, workspace_type FROM workspaces ORDER BY id")
        ).all()
        assert len(rows) == 2
        assert rows[0][1] == "工程"
        assert rows[0][2] == "engineering"
        assert rows[1][1] == "通用"
        assert rows[1][2] == "general"
    upgraded_engine.dispose()


def test_v3_2b_review_brief_migration_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """0009 迁移：Brief 表、ReviewRun Brief 字段、Workspace 约束 → 降级 → 再升级。"""
    database_path = tmp_path / "v3-2b-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)

    # 升级到 0008
    command.upgrade(alembic_config, "20260806_0008")
    engine = create_engine(_sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, status, must_change_password, created_at, updated_at) "
                "VALUES (1, 'v3test', 'hash', 'user', 'active', 0, '2026-08-06', '2026-08-06')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, review_template_key, status, created_at, updated_at) "
                "VALUES (1, 1, '工程', 'engineering', 'engineering_bid_review_v1', 'active', '2026-08-06', '2026-08-06')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, review_template_key, status, created_at, updated_at) "
                "VALUES (2, 1, '通用', 'general', NULL, 'active', '2026-08-06', '2026-08-06')"
            )
        )
    engine.dispose()

    # 升级到 head (0009)
    command.upgrade(alembic_config, HEAD_REVISION)
    upgraded_engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(upgraded_engine)

    # review_briefs 表存在
    assert "review_briefs" in inspector.get_table_names()

    # ReviewRun Brief 字段存在
    assert {
        "review_brief_id",
        "review_brief_version",
        "review_brief_hash",
        "review_brief_snapshot_json",
    }.issubset(_column_names(inspector, "review_runs"))

    # 已有数据完好
    with upgraded_engine.connect() as connection:
        rows = connection.execute(text("SELECT id, name, workspace_type FROM workspaces ORDER BY id")).all()
        assert len(rows) == 2

    # general 不能设置工程模板（新约束）
    import pytest
    with pytest.raises(Exception):
        with upgraded_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE workspaces SET review_template_key = 'engineering_bid_review_v1' WHERE id = 2"
                )
            )

    # engineering + 工程模板通过
    with upgraded_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE workspaces SET review_template_key = 'engineering_bid_review_v1' WHERE id = 1"
            )
        )
    upgraded_engine.dispose()

    # 降级到 0008
    command.downgrade(alembic_config, "20260806_0008")
    downgraded_engine = create_engine(_sqlite_url(database_path))
    downgraded_inspector = inspect(downgraded_engine)
    assert "review_briefs" not in downgraded_inspector.get_table_names()
    assert "review_brief_id" not in _column_names(downgraded_inspector, "review_runs")
    with downgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "20260806_0008"
    downgraded_engine.dispose()

    # 再次 upgrade
    command.upgrade(alembic_config, HEAD_REVISION)
    reupgraded_engine = create_engine(_sqlite_url(database_path))
    with reupgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION
    reupgraded_engine.dispose()


def test_v3_3b_review_report_migration_roundtrip_and_review_data_survives(
    tmp_path: Path, monkeypatch
) -> None:
    """0010 仅增加独立工程报告表；降级和再次升级不影响既有审查数据。"""
    database_path = tmp_path / "v3-3b-review-report-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, "20260806_0009")

    engine = create_engine(_sqlite_url(database_path))
    now = "2026-08-07 00:00:00"
    rule_snapshot = '{"pack_id":"test","rules":[],"version":"1"}'
    brief_snapshot = '{"id":1,"interpreted_json":"{}","version":1}'
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, status, must_change_password, created_at, updated_at) "
                "VALUES (1, 'report-migration', 'hash', 'user', 'active', 0, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, review_template_key, status, created_at, updated_at) "
                "VALUES (1, 1, '工程', 'engineering', 'engineering_bid_review_v1', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO files (id, owner_user_id, filename, file_type, file_path, status, created_at, updated_at) "
                "VALUES (1, 1, '材料.pdf', 'pdf', 'storage/uploads/material.pdf', 'ready', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO workspace_files (id, workspace_id, file_id, created_at, updated_at) "
                "VALUES (1, 1, 1, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO review_runs (id, workspace_id, owner_user_id, review_template_key, status, "
                "rule_pack_id, rule_pack_version, rule_pack_hash, rule_snapshot_json, review_brief_version, "
                "review_brief_hash, review_brief_snapshot_json, created_at, updated_at) "
                "VALUES (1, 1, 1, 'engineering_bid_review_v1', 'completed', 'test', '1', :hash, :rules, "
                "1, :hash, :brief, :now, :now)"
            ),
            {
                "hash": "a" * 64,
                "rules": rule_snapshot,
                "brief": brief_snapshot,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO evidences (id, review_run_id, workspace_id, owner_user_id, file_id, locator_type, "
                "page_number, quote, content_hash, parser_name, parser_version, created_at) "
                "VALUES (1, 1, 1, 1, 1, 'pdf_page', 1, '引用', :hash, 'parser', '1', :now)"
            ),
            {"hash": "b" * 64, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO review_findings (id, review_run_id, workspace_id, owner_user_id, issue_code, title, "
                "category, severity, conclusion, suggestion, rule_id, rule_version, evidence_ids_json, status, created_at) "
                "VALUES (1, 1, 1, 1, 'T-1', '问题', 'test', 'high', '结论', '建议', 'R-1', '1', '[1]', "
                "'confirmed', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO review_actions (id, review_finding_id, review_run_id, workspace_id, owner_user_id, "
                "action_type, created_at) VALUES (1, 1, 1, 1, 1, 'confirm', :now)"
            ),
            {"now": now},
        )
    engine.dispose()

    command.upgrade(alembic_config, HEAD_REVISION)
    upgraded_engine = create_engine(_sqlite_url(database_path))
    upgraded_inspector = inspect(upgraded_engine)
    assert V3_3B_TABLES.issubset(upgraded_inspector.get_table_names())
    with upgraded_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM review_runs")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM evidences")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM review_findings")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM review_actions")).scalar_one() == 1
    upgraded_engine.dispose()

    command.downgrade(alembic_config, "20260806_0009")
    downgraded_engine = create_engine(_sqlite_url(database_path))
    downgraded_inspector = inspect(downgraded_engine)
    assert V3_3B_TABLES.isdisjoint(downgraded_inspector.get_table_names())
    with downgraded_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM review_runs")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM evidences")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM review_findings")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM review_actions")).scalar_one() == 1
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "20260806_0009"
    downgraded_engine.dispose()

    command.upgrade(alembic_config, HEAD_REVISION)
    reupgraded_engine = create_engine(_sqlite_url(database_path))
    with reupgraded_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert connection.execute(text("SELECT COUNT(*) FROM review_runs")).scalar_one() == 1
    assert revision == HEAD_REVISION
    reupgraded_engine.dispose()

def test_v4c2_verification_migration_roundtrip_and_cascade(
    tmp_path: Path, monkeypatch
) -> None:
    """0011 增加工程 Verification 两张表；降级/再次升级不影响既有审查数据；
    级联删除（workspace 删除 → verification run 与 tool call 一并清除）。"""
    database_path = tmp_path / "v4c2-verification-roundtrip.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)
    command.upgrade(alembic_config, "20260807_0010")

    engine = create_engine(_sqlite_url(database_path))
    now = "2026-08-08 00:00:00"
    rule_snapshot = '{"pack_id":"test","rules":[],"version":"1"}'
    brief_snapshot = '{"id":1,"interpreted_json":"{}","version":1}'
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, status, must_change_password, created_at, updated_at) "
                "VALUES (1, 'v4c2-migration', 'hash', 'user', 'active', 0, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name, workspace_type, review_template_key, status, created_at, updated_at) "
                "VALUES (1, 1, '工程', 'engineering', 'engineering_bid_review_v1', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO files (id, owner_user_id, filename, file_type, file_path, status, created_at, updated_at) "
                "VALUES (1, 1, '材料.pdf', 'pdf', 'storage/uploads/material.pdf', 'ready', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO review_runs (id, workspace_id, owner_user_id, review_template_key, status, "
                "rule_pack_id, rule_pack_version, rule_pack_hash, rule_snapshot_json, review_brief_version, "
                "review_brief_hash, review_brief_snapshot_json, created_at, updated_at) "
                "VALUES (1, 1, 1, 'engineering_bid_review_v1', 'completed', 'test', '1', :hash, :rules, "
                "1, :hash, :brief, :now, :now)"
            ),
            {"hash": "a" * 64, "rules": rule_snapshot, "brief": brief_snapshot, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO review_findings (id, review_run_id, workspace_id, owner_user_id, issue_code, title, "
                "category, severity, conclusion, suggestion, rule_id, rule_version, evidence_ids_json, status, created_at) "
                "VALUES (1, 1, 1, 1, 'T-1', '问题', 'test', 'high', '结论', '建议', 'R-1', '1', '[1]', "
                "'pending_review', :now)"
            ),
            {"now": now},
        )
    engine.dispose()

    command.upgrade(alembic_config, HEAD_REVISION)
    upgraded_engine = create_engine(_sqlite_url(database_path))
    upgraded_inspector = inspect(upgraded_engine)
    assert V4C2_TABLES.issubset(upgraded_inspector.get_table_names())
    verification_columns = _column_names(upgraded_inspector, "review_verification_runs")
    assert {
        "id", "workspace_id", "owner_user_id", "review_run_id", "status",
        "input_state_hash", "plan_json", "planner_type", "fallback_used",
        "model_provider", "model_name", "prompt_version", "token_usage_json",
        "tool_budget", "tool_calls_used", "candidate_count", "warning_count",
        "error_code", "error_message", "started_at", "completed_at", "created_at",
    }.issubset(verification_columns)
    tool_columns = _column_names(upgraded_inspector, "review_tool_calls")
    assert {
        "verification_run_id", "review_run_id", "review_finding_id", "workspace_id",
        "owner_user_id", "node_name", "tool_name", "attempt_number", "retry_of_id",
        "status", "input_json", "output_json", "error_code", "error_message",
        "latency_ms", "index_sha256", "corpus_sha256", "model_revision",
        "created_at", "completed_at",
    }.issubset(tool_columns)
    with upgraded_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO review_verification_runs (id, workspace_id, owner_user_id, review_run_id, status, "
                "input_state_hash, planner_type, tool_budget, tool_calls_used, candidate_count, "
                "warning_count, created_at) "
                "VALUES (1, 1, 1, 1, 'completed', :hash, 'deterministic', 5, 1, 3, 0, :now)"
            ),
            {"hash": "c" * 64, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO review_tool_calls (id, verification_run_id, review_run_id, review_finding_id, "
                "workspace_id, owner_user_id, tool_name, attempt_number, status, input_json, created_at) "
                "VALUES (1, 1, 1, 1, 1, 1, 'engineering_hybrid_retrieval', 1, 'success', '{}', :now)"
            ),
            {"now": now},
        )
    upgraded_engine.dispose()

    # 降级到 0010：两张表消失，既有数据保留
    command.downgrade(alembic_config, "20260807_0010")
    downgraded_engine = create_engine(_sqlite_url(database_path))
    downgraded_inspector = inspect(downgraded_engine)
    assert V4C2_TABLES.isdisjoint(downgraded_inspector.get_table_names())
    with downgraded_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM review_runs")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM review_findings")).scalar_one() == 1
    downgraded_engine.dispose()

    # 再次升级：回到 head，两张表恢复；既有审查数据仍在
    # （verification 数据因降级 drop 表而丢失，属预期行为，与 0010 测试一致）
    command.upgrade(alembic_config, HEAD_REVISION)
    reupgraded_engine = create_engine(_sqlite_url(database_path))
    reupgraded_inspector = inspect(reupgraded_engine)
    assert V4C2_TABLES.issubset(reupgraded_inspector.get_table_names())
    with reupgraded_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM review_runs")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM review_findings")).scalar_one() == 1
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == HEAD_REVISION

    # 重新插入 verification 数据后验证级联删除：
    # 删除 workspace → verification run + tool call 一并清除
    # （生产 session 开启 PRAGMA foreign_keys=ON，测试中同步开启以验证 FK 级联契约）
    with reupgraded_engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = ON"))
        connection.execute(
            text(
                "INSERT INTO review_verification_runs (id, workspace_id, owner_user_id, review_run_id, status, "
                "input_state_hash, planner_type, tool_budget, tool_calls_used, candidate_count, "
                "warning_count, created_at) "
                "VALUES (1, 1, 1, 1, 'completed', :hash, 'deterministic', 5, 1, 3, 0, :now)"
            ),
            {"hash": "c" * 64, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO review_tool_calls (id, verification_run_id, review_run_id, review_finding_id, "
                "workspace_id, owner_user_id, tool_name, attempt_number, status, input_json, created_at) "
                "VALUES (1, 1, 1, 1, 1, 1, 'engineering_hybrid_retrieval', 1, 'success', '{}', :now)"
            ),
            {"now": now},
        )
        connection.execute(text("DELETE FROM workspaces WHERE id = 1"))
    with reupgraded_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM review_verification_runs")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM review_tool_calls")).scalar_one() == 0
    reupgraded_engine.dispose()



def _build_alembic_config(database_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", _sqlite_url(database_path))
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("LLM_API_KEY", "")
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def _sqlite_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.resolve().as_posix()}"


def _column_names(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}
