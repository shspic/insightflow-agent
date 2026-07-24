from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import BACKEND_DIR, settings
from app.db.base import Base


def ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    database_path = unquote(database_url.removeprefix("sqlite:///"))

    if database_path in ("", ":memory:"):
        return

    path = Path(database_path)
    if not path.is_absolute():
        path = BACKEND_DIR / database_path

    path.parent.mkdir(parents=True, exist_ok=True)


ensure_sqlite_parent_dir(settings.database_url)

connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=max(60, settings.database_pool_recycle_seconds),
)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={max(1000, settings.sqlite_busy_timeout_ms)}")
        if settings.database_url not in {"sqlite://", "sqlite:///:memory:"}:
            journal_mode = (
                settings.sqlite_journal_mode
                if settings.sqlite_journal_mode
                in {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"}
                else "WAL"
            )
            cursor.execute(f"PRAGMA journal_mode={journal_mode}")
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
