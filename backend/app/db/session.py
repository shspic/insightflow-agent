from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import BACKEND_DIR, settings


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

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
