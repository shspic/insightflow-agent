from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_DIR, settings
from app.db.session import ensure_sqlite_parent_dir


def init_db() -> None:
    ensure_sqlite_parent_dir(settings.database_url)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_config, "head")


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成，Alembic 已升级到最新 revision。")
