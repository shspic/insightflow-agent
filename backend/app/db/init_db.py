from app.db.session import Base, engine, ensure_sqlite_parent_dir
from app.core.config import settings
from app.models import File, FileChunk, Task, ToolCall


def init_db() -> None:
    ensure_sqlite_parent_dir(settings.database_url)
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成，基础表已创建。")
