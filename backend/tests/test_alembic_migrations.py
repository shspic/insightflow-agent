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
HEAD_REVISION = "20260724_0005"
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
}


def test_alembic_upgrade_head_creates_v2_schema(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "fresh.db"
    alembic_config = _build_alembic_config(database_path, monkeypatch)

    command.upgrade(alembic_config, "head")

    engine = create_engine(_sqlite_url(database_path))
    inspector = inspect(engine)
    assert V2_TABLES.issubset(inspector.get_table_names())
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
