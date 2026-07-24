# V2-07 日常运维、备份、升级与回滚手册

以下命令在服务器 `/opt/insightflow/current` 执行。真实 `.env`、数据库和证书不进入 Git。

## 1. 服务与日志

```bash
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml ps
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml up -d
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml stop
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml restart backend
```

```bash
# 最近全部日志
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml logs --tail=200
# 分服务
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml logs -f backend
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml logs -f worker
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml logs -f web
```

Docker stdout/stderr 每服务 `10m × 5` 轮转；Nginx、部署、备份和清理文件日志由 `deploy/logrotate/insightflow` 每日轮转 14 份。日志只记录运行元数据；不得新增密码、Token、邀请码、API Key、完整文档或模型正文。Worker 日志保留 `worker_id` 和 `task_id`。

## 2. 健康检查

```bash
sudo bash deploy/scripts/healthcheck.sh
echo $?
```

退出 0 表示所有检查通过；非零值是异常项数量。`readiness=degraded` 仍允许服务，但必须查看 DeepSeek/OCR 明细：

```bash
curl -fsS https://<域名>/api/health
curl -fsS https://<域名>/api/health/ready
```

## 3. 备份

```bash
sudo bash deploy/scripts/backup.sh
```

每个备份包含 SQLite Online Backup API 生成的一致性 `database.sqlite3`、完整 `storage.zip` 和记录大小/SHA-256 的 `manifest.json`；不包含 `.env`、证书和密钥。建议每日备份，默认工程保留目标 30 天，但脚本不会批量自动删除旧备份。管理员每月人工核对清单后，一次处理一个明确目录。

本机备份无法应对整块磁盘或整台服务器损坏。预算有限时至少每周把加密后的最新备份和 manifest 下载到另一台设备，并每月做一次离线恢复演练。

校验：

```bash
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml \
  exec -T backend python -m app.maintenance.backup \
  --verify /app/backups/<备份目录名>
```

恢复演练不要覆盖生产库：

```bash
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml \
  exec -T backend python -m app.maintenance.restore \
  --backup-dir /app/backups/<备份目录名> \
  --destination /app/backups/<备份目录名>/restore-drill.sqlite3
```

该命令若目标已存在会拒绝覆盖。演练后按项目单文件删除规则人工处理该明确副本。

## 4. 清理

上线初期长期使用：

```bash
sudo bash deploy/scripts/cleanup.sh
```

输出记录扫描/删除数量、释放字节和错误数。只有连续 dry-run 结果经过人工确认、已完成最近备份、保留期符合产品政策、当前报告/活跃文件保护测试通过时，才允许：

```bash
sudo CONFIRM_CLEANUP=APPLY_CLEANUP bash deploy/scripts/cleanup.sh --apply
```

清理失败只返回非零并记录日志，不停止应用。它处理 Session、孤立失败上传、过期事件/AgentRun、软删除工作区和被替代报告资产，不按时间删除活跃文件和当前报告。

## 5. 升级

先把新发布包放到新的只读 release 目录，或提前 `docker load` 镜像；不要在当前 release 上原地覆盖。升级命令：

```bash
cd /opt/insightflow/releases/<新版本>
sudo bash deploy/scripts/upgrade.sh <新版本>
```

顺序固定：

1. 校验环境和 Compose；
2. 在仍运行的旧版本上创建数据库/storage 备份；
3. 构建新镜像，或使用已加载的不可变镜像；
4. 停止 backend/worker 写入，Nginx 暂时保留；
5. 对持久库执行 `alembic upgrade head`，绝不删除数据库；
6. 启动 backend/worker；
7. readiness 通过后更新 web；
8. `nginx -t`，记录版本。

迁移或 readiness 失败时不要继续切换 Nginx，不要反复执行迁移，保留现场并进入回滚判断。

## 6. 回滚

### 6.1 仅代码回滚

只在旧代码明确兼容当前数据库 schema 时：

```bash
sudo bash deploy/scripts/rollback.sh --code-only \
  <旧backend镜像:不可变标签> <旧web镜像:不可变标签>
```

### 6.2 数据库迁移不可安全回滚

不能承诺所有 Alembic downgrade 都无损。默认恢复策略是使用升级前同一备份的数据库和 storage，再启动对应旧代码：

```bash
sudo CONFIRM_RESTORE=RESTORE_DATABASE_AND_STORAGE \
  bash deploy/scripts/rollback.sh --restore-backup \
  <旧backend镜像:不可变标签> <旧web镜像:不可变标签> <备份目录名>
```

脚本先校验 manifest/SHA 和数据库一致性，停止写入，把当前数据库和整个 storage 移到新的 `rollback-safety-*` 目录，然后恢复备份。现场不会被删除。恢复后仍需人工核对登录、任务、报告和文件。

### 6.3 数据库可兼容回滚

若迁移说明明确是向后兼容扩展，可只回代码；否则按完整恢复处理。不要自行执行 `alembic downgrade`，除非该 revision 已在生产副本上完成专门演练和数据损失评审。

## 7. 证书、管理员与 DeepSeek

证书更新：

```bash
sudo bash deploy/scripts/reload-nginx.sh
```

管理员创建/密码更新必须继续使用安全 CLI：

```bash
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml \
  run --rm --no-deps backend python -m app.cli.create_admin
```

轮换 DeepSeek Key 时编辑权限为 `0600` 的 `deploy/.env.production`，然后只重建 API/Worker 容器并检查 readiness：

```bash
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml \
  up -d --force-recreate backend worker
sudo bash deploy/scripts/healthcheck.sh
```

旧 Key 在新 Key 验证成功后于服务商控制台人工撤销。不要把 Key 作为命令参数、提交到 Git 或写入日志。

## 8. 定时任务

仓库提供 systemd timer：

- `insightflow-backup.timer`：每日备份；
- `insightflow-health.timer`：每 15 分钟健康检查；
- `insightflow-cleanup-dry-run.timer`：每周清理预演。

如果使用 Cron，可等价配置，但必须使用绝对路径并把输出写到受限日志目录。自动 apply 清理默认禁止。
