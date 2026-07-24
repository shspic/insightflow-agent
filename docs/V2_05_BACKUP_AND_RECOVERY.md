# V2-05 SQLite 备份与恢复

## 原则

当前工具面向 SQLite 单机阶段。普通数据备份默认不包含 `.env`、API Key 或明文 Session Token。备份目录已被 Git 忽略，不得提交。

## 创建一致性备份

建议先暂停写入和 Worker，再执行：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m app.maintenance.backup
```

工具使用 SQLite backup API 生成一致数据库副本，归档 `backend/storage`，并生成 `manifest.json`。manifest 包含时间、文件大小和 SHA-256。

## 校验

```powershell
.\.venv\Scripts\python.exe -m app.maintenance.backup --verify .\backups\insightflow-backup-时间戳
```

校验包括 manifest、文件哈希和 `PRAGMA integrity_check`。

## 恢复前检查

1. 停止 API 和 Worker；
2. 确认备份校验通过；
3. 记录当前数据库和 storage 位置；
4. 确认恢复目标路径不存在；
5. 确认磁盘空间充足；
6. 记录 `alembic heads` 和备份数据库的 `alembic current`。

## 恢复数据库副本

```powershell
.\.venv\Scripts\python.exe -m app.maintenance.restore `
  --backup-dir .\backups\insightflow-backup-时间戳 `
  --destination .\data\restored-app.db
```

工具默认拒绝覆盖现有文件。先使用新的 `DATABASE_URL` 启动隔离实例并检查 health、revision、用户登录、任务和报告。确认后再由负责人安排停机切换。storage.zip 也应先解压到新目录核对，不要直接覆盖生产目录。

## 恢复演练

至少每季度执行一次：备份、校验、恢复到新路径、运行 Alembic current、启动隔离 API、下载一份合成报告。记录实际恢复点和恢复时间，不要把测试输出提交 Git。

## 国内部署后的升级

正式国内部署后必须迁移到异地云盘、对象存储版本化或独立备份服务，并配置加密、生命周期、不可变备份、监控和定期恢复演练。当前本机备份不是生产灾备平台。
