from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import unquote

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402,F401


target_metadata = Base.metadata


def _resolve_database_url() -> str:
    command_options = context.get_x_argument(as_dictionary=True)
    database_url = (
        command_options.get("database_url")
        or os.getenv("ALEMBIC_DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
    )
    if not database_url:
        raise RuntimeError("未配置 Alembic 数据库地址")

    if not database_url.startswith("sqlite:///"):
        return database_url

    database_path = unquote(database_url.removeprefix("sqlite:///"))
    if database_path in ("", ":memory:"):
        return database_url

    path = Path(database_path)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def run_migrations_offline() -> None:
    database_url = _resolve_database_url()
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=database_url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
