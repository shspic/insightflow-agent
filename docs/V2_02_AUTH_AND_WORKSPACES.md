# V2-02 认证、管理员、工作区与多用户数据隔离

> 阶段状态：已实现代码和自动化测试；真实 `backend/data/app.db` 未自动升级。

## 1. 目标和范围

V2-02 在 V2-01 迁移基线上完成登录、邀请码注册、人工密码重置、管理员最小后台、工作区和资源归属隔离。任务执行继续复用当前同步 LangGraph 和已有文件服务。

本阶段没有实现 Supervisor、专业子 Agent、异步队列、SSE、任务暂停恢复、文件关系识别或 Word/PDF 新导出能力。

## 2. 架构

```text
React + React Router
  └─ 相对 /api/v2 + credentials: include + X-CSRF-Token
      └─ FastAPI V2 路由
          ├─ 认证依赖：Session Hash → active user → must_change_password → role
          ├─ 管理员服务：邀请码、重置申请、用户状态、脱敏审计
          ├─ 工作区 owner 查询
          └─ 现有解析 / OCR / RAG / LangGraph / 报告服务
              ├─ SQLite + Alembic
              └─ 本地文件存储（后续可替换对象存储）
```

所有 V2 私有资源从 Session 推导当前用户，不接受客户端提交 `owner_user_id`。工作区、文件和任务查询在 SQL 条件中同时包含资源 ID、工作区 ID 和当前用户 ID。管理员使用普通用户能力时也只能访问自己的工作区。

## 3. 密码、Session Cookie 与 CSRF

- 密码使用 `argon2-cffi` 的 Argon2id 默认安全参数；数据库只保存 `password_hash`。
- 本阶段实际环境为 Python 3.14.4，安装并验证了 `argon2-cffi 25.1.0`；该版本的官方发布信息声明支持 Python 3.14。
- Session Token 使用 `secrets.token_urlsafe(48)` 生成，浏览器只通过 HttpOnly Cookie 保存，数据库只保存 SHA-256 Token Hash。
- CSRF Token 与 Session Token 不同。登录后数据库 Session 保存 CSRF Token Hash，浏览器保存可读的 CSRF Cookie，修改请求必须同时提交同值 `X-CSRF-Token` Header。
- 登录、注册和匿名重置申请先通过 `/api/v2/auth/csrf` 获取带时间戳和 HMAC 签名的公共 CSRF Token。
- 修改密码会撤销用户全部旧 Session，并在同一流程中创建新 Session。
- `last_seen_at` 默认至少间隔 300 秒才写一次，避免每个请求都更新数据库。
- 本地 HTTP 默认 `AUTH_COOKIE_SECURE=false`；生产环境必须使用 HTTPS 并设置为 `true`。

`AUTH_SECRET_KEY` 用于 HMAC 和限流标识摘要。生产环境长度不足 32 字符、未启用 Secure Cookie 或仍启用 Legacy V1 时，应用会明确拒绝启动。

## 4. 注册、登录和强制改密

注册：

```text
公共 CSRF → username/password/password_confirm/invite_code
→ 校验邀请码 HMAC、状态、次数和过期时间
→ 创建普通用户并原子增加 used_count
```

登录只需要账号和密码。失败响应统一为“账号或密码错误”，不区分账号不存在、密码错误或账号禁用。

`must_change_password=true` 时，只允许访问：

- `GET /api/v2/auth/me`
- `POST /api/v2/auth/logout`
- `POST /api/v2/auth/change-password`

其他私有接口返回 `PASSWORD_CHANGE_REQUIRED`。

## 5. 邀请码

管理员通过 `POST /api/v2/admin/invite-codes` 创建邀请码。原始值只在创建响应中出现一次，数据库保存：

- 以 `AUTH_SECRET_KEY` 为密钥的 HMAC-SHA256；
- 不可还原完整值的 `code_hint`；
- 状态、最大使用次数、已使用次数和过期时间。

状态支持 `active`、`disabled`、`exhausted`、`expired`。轮换会直接替换摘要和提示、清零使用次数，旧值立即失效。列表接口不返回原值或摘要。

## 6. 人工密码重置

```text
用户匿名提交统一提示的申请
→ 管理员查看 pending
→ 管理员生成一次性临时密码
→ 临时密码立即作为用户新密码进行 Argon2id 哈希
→ 设置 must_change_password=true 并撤销全部 Session
→ 明文只在本次管理员响应出现
→ 用户以临时密码登录并强制修改
→ 再次撤销旧 Session、建立新 Session
→ approved 申请更新为 completed
```

数据库、审计日志和列表接口都不保存或返回明文临时密码。管理员刷新页面后无法再次取得。

## 7. 管理员初始化

交互方式：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m app.cli.create_admin
```

密码通过 `getpass` 输入，不回显。已存在账号不会静默覆盖。

更新已存在管理员密码：

```powershell
.\.venv\Scripts\python.exe -m app.cli.create_admin --username <账号> --update-password
```

非交互部署只能通过 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 环境变量输入，并应搭配 `--yes`。命令不会输出密码。不要把这两个变量写入仓库。

## 8. 登录与申请限流

`auth_rate_limits` 持久化以下 HMAC 摘要范围，不保存原密码或完整邀请码：

- 账号登录失败；
- IP 登录失败；
- IP 注册尝试；
- 账号和 IP 重置申请。

阈值、窗口和锁定时间均由环境变量控制。该方案适合单机 SQLite 和 5 人以内低并发；多进程或多实例部署前需要重新验证事务竞争并改为共享限流存储。

## 9. 工作区、文件和任务隔离

- 工作区以 `owner_user_id` 归属，支持归档和永久删除。永久删除需完整名称确认，不可恢复。历史软删除数据不会自动清理。
- 新上传文件写入 `files.owner_user_id`，同时创建唯一的 `workspace_files` 关联。
- 文件详情、解析、分析、图表、索引、搜索、OCR、原文件下载和图表资源下载都先做 owner + workspace + association 校验。
- 新任务的 `owner_user_id` 来自 Session，`workspace_id` 必须属于当前用户，文件列表必须全部来自该工作区。
- 轨迹通过已鉴权任务继承归属；报告读取和下载再次校验 task + workspace + owner。
- V2 响应移除 `file_path`、`report_path`、绝对路径和轨迹 JSON 中的路径键。
- 管理员没有读取其他用户工作区或文件的旁路。

从工作区移除单个文件时，仅删除该工作区关联，原始文件保留以供其他工作区继续使用。永久删除整个工作区时，会在数据库提交成功后清理不再被其他工作区引用的上传文件及报告资产；共享文件因仍有关联而继续保留。磁盘清理失败通过 `storage_cleanup_warnings` 返回以供排查，不影响数据库删除结果。

永久删除安全边界：
- 数据库删除成功但个别磁盘文件清理失败时，会返回 `storage_cleanup_warnings` 供排查。
- 永久删除表示产品层面不可恢复；不代表密码学擦除、安全擦除或底层存储介质不可恢复。
- 历史软删除数据不会自动清理。

## 10. Legacy V1

`ENABLE_LEGACY_V1_API=true` 时保留旧 `/api/files`、`/api/tasks`、`/api/reports` 和 `/static/charts`，用于本地兼容。旧接口没有完整多用户隔离，不得用于正式公网。

生产环境必须：

```text
ENV=production
ENABLE_LEGACY_V1_API=false
AUTH_COOKIE_SECURE=true
```

## 11. 新数据库初始化

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m app.cli.create_admin
```

## 12. 已有数据库升级

先停止后端写入并备份：

```powershell
cd D:\spir\NO2_agent\backend
$backupName = "app.db.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Copy-Item -LiteralPath ".\data\app.db" -Destination ".\data\$backupName"
Get-Item -LiteralPath ".\data\$backupName"
```

检查：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini current
.\.venv\Scripts\alembic.exe -c alembic.ini heads
```

如果数据库是未纳管的旧四表结构，人工确认与 `20260723_0001` 一致后：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini stamp 20260723_0001
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
```

如果已经在 `20260723_0002`：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
```

不要删除 `app.db`，不要对结构不明的数据库强行 stamp。

## 13. 迁移与回滚

V2-02 新迁移：

- revision：`20260723_0003`
- 新表：`auth_rate_limits`
- `auth_sessions`：增加 `csrf_token_hash`
- `files`：增加 `mime_type`、`size_bytes`
- `invite_codes`：状态约束增加 `exhausted`、`expired`

只回退 V2-02：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini downgrade 20260723_0002
```

回退会删除限流记录和新增字段，并把 `exhausted`、`expired` 邀请码状态规范为 `active` 以兼容旧约束。已有真实认证流量后不建议直接回退；必须先备份并评估会话和邀请码状态。

## 14. 旧数据认领

默认只预览：

```powershell
.\.venv\Scripts\python.exe -m app.cli.claim_legacy_data --username <账号> --dry-run
```

显式执行：

```powershell
.\.venv\Scripts\python.exe -m app.cli.claim_legacy_data --username <账号> --apply
```

工具只处理 owner 为空的旧文件和任务，创建“旧版数据”工作区，重复执行不会重复关联；不会在应用启动时自动运行。

## 15. 本地启动

后端：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

前端：

```powershell
cd D:\spir\NO2_agent\frontend
npm install
npm run dev
```

Vite 将 `/api` 转发到 `http://127.0.0.1:8000`。前端默认使用相对地址；只有兼容特殊部署时才配置 `VITE_API_BASE_URL`。

## 16. 当前未实现与下一阶段

仍未实现：Supervisor、专业子 Agent、异步队列、SSE、任务取消和局部重试、计划确认、文件关系识别、Markdown 上传、Word/PDF 新导出、最终 UI 美化。

下一阶段建议优先做统一文件理解：补齐 Markdown，持久化结构摘要、文件角色和关系候选，提供用户确认修正，并把这些结构化输入交给后续计划与异步执行层。

## 17. 本阶段验证结果

- 后端全量：`28 passed`。
- Alembic head：`20260723_0003`。
- 独立临时 SQLite：从零升级到 head、回退到 `20260723_0002`、再次升级到 head 均成功。
- 真实开发库只读检查：当前为 `20260723_0002`，本阶段未自动升级。
- 前端生产构建：Vite 成功转换 64 个模块。
- 已知警告：项目沿用的 `datetime.utcnow()` 在 Python 3.14 产生弃用警告；TestClient 依赖产生一条弃用警告。未为消除警告而扩大本阶段重构范围。
