# V2-01 数据库迁移基线、用户体系与工作区数据模型

> 阶段状态：已实现数据库迁移和 ORM 数据基础，尚未实现认证与业务接口
> 适用目录：`backend`
> 正式迁移入口：Alembic

## 1. 本阶段目标

V2-01 为后续登录、权限隔离、邀请码、人工密码重置和工作区功能建立可迁移的数据基础。本阶段只完成：

- Alembic 配置和两阶段迁移；
- 用户、Session、邀请码、密码重置、工作区、工作区文件关联和审计日志 ORM；
- 现有 `files`、`tasks` 的可空归属字段；
- 迁移与模型测试；
- `init_db` 到 Alembic 的兼容入口。

本阶段没有创建默认管理员、真实密码、邀请码、Session Token 或 DeepSeek API Key。

## 2. 两阶段迁移

### 2.1 迁移 1：当前结构基线

- revision：`20260723_0001`
- 文件：`backend/alembic/versions/20260723_0001_current_schema_baseline.py`
- 内容：按当前真实代码创建 `files`、`tasks`、`tool_calls`、`file_chunks`。

用途：

- 新数据库可以从零创建当前四张基础表。
- 已有数据库确认结构与当前基线一致后，可以 `stamp` 到该 revision，避免重复创建已有表。
- 该迁移不包含 V2 用户或工作区结构。

### 2.2 迁移 2：V2 身份与工作区基础

- revision：`20260723_0002`
- 文件：`backend/alembic/versions/20260723_0002_v2_identity_workspace_foundation.py`
- 内容：新增七张 V2 表，并向 `files`、`tasks` 增加可空归属字段。

SQLite 的表变更使用 Alembic batch mode。迁移没有删除或重命名现有字段，也没有创建 legacy/default 用户或自动认领旧数据。

## 3. 新增数据表

| 表 | 用途 | 敏感数据约束 |
| --- | --- | --- |
| `users` | 登录账号、密码哈希、角色、账号状态和强制改密状态 | 只保存 `password_hash`，不保存明文密码 |
| `auth_sessions` | 可过期、可撤销的登录会话 | 只保存 `token_hash`，不保存 Session Token |
| `invite_codes` | 注册邀请码的状态、用量和创建人 | 只保存 `code_hash` 和不可还原完整邀请码的 `code_hint` |
| `password_reset_requests` | 用户申请、管理员处理和完成状态 | 不保存明文临时密码 |
| `workspaces` | 用户拥有的工作区和软删除状态 | `owner_user_id` 必填 |
| `workspace_files` | 工作区与文件关联、系统角色和用户确认角色 | 同一文件在同一工作区只能关联一次 |
| `audit_logs` | 登录、注册、邀请码、重置、文件访问和管理操作审计 | 禁止记录密码、完整邀请码、Token、API Key 和文件敏感原文 |

### 3.1 关键状态

- `users.role`：`user`、`admin`。
- `users.status`：`active`、`disabled`。
- `invite_codes.status`：`active`、`disabled`。
- `password_reset_requests.status`：`pending`、`approved`、`rejected`、`completed`。
- `workspaces.status`：`active`、`archived`。

这些状态目前通过数据库 CheckConstraint 约束。管理员仍必须经过认证；管理员只是不受后续普通配额限制，不绕过权限和安全检查。

## 4. 现有表新增字段

| 表 | 新增字段 | 是否可空 | 原因 |
| --- | --- | --- | --- |
| `files` | `owner_user_id` | 是 | 保留旧数据兼容，后续认证阶段再设计回填 |
| `tasks` | `owner_user_id` | 是 | 保留旧任务兼容 |
| `tasks` | `workspace_id` | 是 | 后续任务进入工作区作用域 |

`tool_calls` 继续通过 `task_id` 继承归属，`file_chunks` 继续通过 `file_id` 继承归属。本阶段没有重复增加 owner 字段。

## 5. 表关系

```text
users
  ├─< auth_sessions
  ├─< invite_codes.created_by_user_id
  ├─< password_reset_requests.user_id
  ├─< password_reset_requests.handled_by_user_id
  ├─< workspaces.owner_user_id
  ├─< files.owner_user_id（当前可空）
  ├─< tasks.owner_user_id（当前可空）
  └─< audit_logs.user_id（允许匿名或已删除用户）

workspaces
  ├─< workspace_files >─ files
  └─< tasks.workspace_id（当前可空）

tasks
  └─< tool_calls

files
  └─< file_chunks
```

关键约束：

- `users.username` 唯一索引；
- `auth_sessions.token_hash` 唯一索引；
- `invite_codes.code_hash` 唯一索引；
- `workspace_files(workspace_id, file_id)` 唯一约束；
- 常用外键、状态和时间字段建立索引。

时间字段沿用当前项目的 `datetime.utcnow` 和无时区 `DateTime` 策略。本阶段不单独重构全项目时间语义。

## 6. 为什么先做迁移与隔离基础

当前文件、任务、轨迹和报告都是全局资源，没有 owner 或工作区边界。如果先实现登录接口或新业务功能，后续很容易出现：

- 新数据无法确定归属；
- 详情、下载和任务接口遗漏用户过滤；
- 旧数据被错误分配给第一个注册用户；
- 直接修改 SQLite 导致环境结构不一致；
- 无法安全回滚数据库变化。

因此 V2 先建立版本化迁移和数据关系，但暂不自动回填旧数据。legacy/default 用户和安全初始化命令留到认证阶段设计。

## 7. 新数据库初始化

适用于新克隆项目且 `backend/data/app.db` 不存在。

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c alembic.ini current
```

默认会使用 `backend/alembic.ini` 中的相对地址 `sqlite:///./data/app.db`。Alembic `env.py` 会相对于 `backend` 解析该路径，不依赖真实 `backend/.env`，也不硬编码本机绝对路径。

如需指定独立数据库：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini -x database_url=sqlite:///D:/temporary/insightflow-v2.db upgrade head
```

也可以使用临时环境变量 `ALEMBIC_DATABASE_URL`。测试或临时验证必须使用独立路径，不要把覆盖地址指向真实 `app.db`。

## 8. 已有数据库升级

适用于已经存在当前四张核心表、但还没有 `alembic_version` 的 `backend/data/app.db`。

### 8.1 停止写入

先停止后端和其他可能写数据库的进程。

### 8.2 备份

```powershell
cd D:\spir\NO2_agent\backend
$backupName = "app.db.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Copy-Item -LiteralPath ".\data\app.db" -Destination ".\data\$backupName"
```

确认备份文件存在且大小合理：

```powershell
Get-Item -LiteralPath ".\data\$backupName"
```

### 8.3 确认 revision

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini current
.\.venv\Scripts\alembic.exe -c alembic.ini heads
```

旧数据库没有 `alembic_version` 时，`current` 不会显示 revision。执行 `stamp` 前必须确认数据库确实是当前项目的四表结构；如果表或字段与 `docs/PROJECT_AUDIT.md` 不一致，应停止并单独处理，不能强行 stamp。

### 8.4 标记基线并增量升级

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini stamp 20260723_0001
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c alembic.ini current
```

`stamp` 只写入 revision 标记，不创建、删除或修改四张旧表；随后第二条迁移只新增表和可空字段。

不要直接对已有、未 stamp 的四表数据库执行 `upgrade head`，否则基线迁移会尝试创建已存在的表并失败。

## 9. Alembic 常用命令

在 `backend` 目录执行：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini current
.\.venv\Scripts\alembic.exe -c alembic.ini history
.\.venv\Scripts\alembic.exe -c alembic.ini heads
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c alembic.ini downgrade 20260723_0001
```

后续生成迁移前必须导入全部模型并人工审查：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini revision --autogenerate -m "说明"
```

禁止未经审查直接在生产数据库运行自动生成迁移。

## 10. 回滚方式

只回退 V2-01 增量迁移：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\alembic.exe -c alembic.ini downgrade 20260723_0001
```

该命令会删除 V2-01 新增的七张表，并移除 `files.owner_user_id`、`tasks.owner_user_id`、`tasks.workspace_id`，但保留原四张表和原字段。

注意：

- 如果新表已经产生真实用户或工作区数据，回退会删除这些新增数据，必须先备份并确认。
- 不要默认通过删除 `app.db` 回滚。
- 如迁移过程异常，应停止应用写入并根据备份制定恢复，不要反复执行未知命令。

## 11. `init_db` 与 Alembic

`python -m app.db.init_db` 保留为兼容入口，但内部已改为执行 `alembic upgrade head`，不再调用 `Base.metadata.create_all()` 绕过迁移。

推荐直接使用 Alembic 命令，因为它能明确显示 revision。对于已有的未纳管数据库，仍然必须先按第 8 节人工确认并 stamp 基线；`init_db` 不会自动猜测旧库结构或自动 stamp。

## 12. 当前仍未实现

- 登录、注册、退出和 Session Cookie；
- 密码哈希生成与校验服务；
- 管理员安全初始化；
- 邀请码创建、校验、消耗和轮换接口；
- 密码重置业务接口和一次性临时密码设置；
- 强制修改密码和旧 Session 撤销逻辑；
- 工作区 CRUD 和权限依赖；
- legacy/default 用户与旧数据回填；
- 文件关系识别；
- 前端登录、注册、工作区和管理员页面；
- Supervisor、子 Agent、队列、SSE 和报告导出。

## 13. 下一阶段建议

下一阶段建议实施“认证服务与安全初始化”：

1. 选择成熟的密码哈希实现；
2. 提供一次性的安全管理员初始化命令，凭据只来自环境变量或交互输入；
3. 实现注册、登录、退出、当前用户和强制修改密码；
4. 实现 Session Token 生成、哈希存储、过期和撤销；
5. 实现邀请码事务校验；
6. 建立 `get_current_user`、`require_admin` 和工作区 owner 权限依赖；
7. 设计旧数据归属的显式认领/回填流程。

在上述功能完成前，新表只是数据基础，不能声称项目已经具备登录或多租户隔离能力。
