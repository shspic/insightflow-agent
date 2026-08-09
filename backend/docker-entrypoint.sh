#!/bin/sh
# 后端容器入口：启动前安全执行 Alembic 迁移（幂等），再启动实际命令。
# - DATABASE_URL 必须指向持久化 volume（/app/data）
# - 迁移失败立即退出（容器进入 unhealthy/restart 循环，不启动半初始化服务）
set -e

echo "[entrypoint] 执行 Alembic 迁移 …"
python -m app.db.init_db

echo "[entrypoint] 迁移完成，启动服务: $*"
exec "$@"
