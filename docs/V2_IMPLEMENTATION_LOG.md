# InsightFlow Agent V2 实施日志

## V2-01：数据库迁移基线、用户体系与工作区数据模型

### 阶段编号

`V2-01`

### 实施内容

- 引入 Alembic，建立当前四表基线迁移和 V2 身份/工作区增量迁移。
- 新增 users、auth_sessions、invite_codes、password_reset_requests、workspaces、workspace_files、audit_logs ORM。
- 为 files 新增可空 `owner_user_id`。
- 为 tasks 新增可空 `owner_user_id`、`workspace_id`。
- 统一模型导出，确保 Alembic metadata 注册全部模型。
- 将 `python -m app.db.init_db` 调整为 Alembic `upgrade head` 兼容入口。
- 增加模型、唯一约束、临时 SQLite 升级、旧数据保留和 downgrade 测试。
- 更新 V2 需求优先级：原 P0 为“V2 必须实现第一批”，原 P1 为“V2 必须实现第二批”，两批均属于正式版必做。

### 修改文件

实施完成时以 Git 差异为准，主要包括：

- `backend/requirements.txt`
- `backend/alembic.ini`
- `backend/alembic/`
- `backend/app/db/init_db.py`
- `backend/app/models/`
- `backend/tests/test_v2_database_models.py`
- `backend/tests/test_alembic_migrations.py`
- `docs/V2_PRODUCT_AND_ARCHITECTURE_PLAN.md`
- `docs/V2_01_DATABASE_MIGRATION.md`
- `docs/V2_IMPLEMENTATION_LOG.md`

### 测试结果

- 后端 pytest：`12 passed`；保留 1 条现有 Starlette TestClient 弃用警告。
- 真实开发库 Alembic `current`：命令成功，未显示 revision，说明当前 `app.db` 尚未纳入 Alembic；未对其执行 stamp 或 upgrade。
- Alembic `heads`：`20260723_0002 (head)`。
- 独立临时 SQLite `upgrade head`：成功到达 `20260723_0002`；七张 V2 表、`files.owner_user_id`、`tasks.owner_user_id`、`tasks.workspace_id` 均存在。
- 临时库 `alembic check`：`No new upgrade operations detected.`。
- 临时旧基线数据升级测试：原 `files`、`tasks` 样例记录升级后仍存在。
- 临时库 downgrade：可从 head 回退到 `20260723_0001`。
- `python -m app.db.init_db`：使用独立临时 SQLite 验证可通过 Alembic 升级到 head。
- 前端 `npm run build`：成功，40 个模块完成生产构建。
- `git diff --check`：通过；仅有 Git 的 LF/CRLF 提示，没有空白错误。
- Git 状态：仅包含本阶段代码/文档改动和任务开始前已存在的未跟踪 `docs/PROJECT_AUDIT.md`；未出现真实 `.env`、数据库或临时验证库。

### 已知限制

- 本阶段只有表和模型，没有认证、授权或业务 API。
- 不创建默认管理员，不回填旧数据 owner。
- 旧数据库首次纳管需要备份并人工 `stamp 20260723_0001`。
- `files.owner_user_id`、`tasks.owner_user_id`、`tasks.workspace_id` 暂时允许空值。
- 时间字段继续沿用项目当前的无时区 UTC 时间策略。
- 未迁移 PostgreSQL，只保持 SQLAlchemy/Alembic 迁移写法兼容。

### 下一阶段入口

建议进入 V2-02：认证服务、安全管理员初始化、Session、邀请码注册和工作区权限依赖。

## V2-02：认证、管理员、工作区和多用户数据隔离

### 阶段编号

`V2-02`

### 实施内容

- 新增 Argon2id 密码哈希、安全 Session Token、HttpOnly Cookie、双 Token CSRF 和持久化数据库限流。
- 新增注册、登录、退出、当前用户、修改密码、撤销会话和匿名密码重置申请接口。
- 新增管理员安全初始化 CLI、邀请码管理、人工临时密码、用户状态、任务元数据和脱敏审计接口。
- 新增工作区 CRUD、软删除/恢复、工作区作用域文件操作、同步任务、轨迹、报告和鉴权下载。
- 新增旧数据认领 CLI，默认 dry-run，显式 `--apply` 才写入。
- 新增正式前端路由、认证页面、强制改密、工作区页面和管理员页面。
- 新增 `20260723_0003` 迁移，为 Session CSRF、文件 MIME/大小和持久化限流提供数据结构。
- 旧 V1 API 通过 `ENABLE_LEGACY_V1_API` 控制；生产环境强制关闭。

### 主要修改文件

- `backend/alembic/versions/20260723_0003_v2_auth_security.py`
- `backend/app/api/v2/`
- `backend/app/api/dependencies/auth.py`
- `backend/app/cli/`
- `backend/app/services/auth_service.py`
- `backend/app/services/security_service.py`
- `backend/app/services/admin_service.py`
- `backend/app/services/workspace_service.py`
- `backend/app/models/auth_rate_limit.py`
- `backend/tests/test_v2_auth.py`
- `backend/tests/test_v2_admin.py`
- `backend/tests/test_v2_workspaces.py`
- `frontend/src/api/`
- `frontend/src/context/AuthContext.jsx`
- `frontend/src/pages/`
- `docs/V2_02_AUTH_AND_WORKSPACES.md`
- `docs/V2_02_MANUAL_ACCEPTANCE.md`

### 测试结果

- 后端 pytest：`28 passed`。
- Alembic head：`20260723_0003`。
- 独立临时 SQLite 完成 `upgrade head → downgrade 20260723_0002 → upgrade head`。
- 真实开发库只读 `current`：`20260723_0002`，未自动升级。
- 前端 `npm run build`：成功，64 个模块完成生产构建。
- `npm install` 报告 1 个低危依赖告警；未自动执行可能扩大改动的 `npm audit fix`。

### 已知限制

- 任务仍为同步 HTTP 执行，没有队列、SSE、取消和局部重试。
- 仍使用当前 V1 LangGraph 单工作流，没有 Supervisor 或专业子 Agent。
- 没有文件关系识别、计划确认、Word/PDF 新导出能力。
- SQLite 限流适合单机低并发；多实例部署前需迁移到共享限流存储或数据库锁策略。
- 旧 V1 接口没有完整隔离，只允许本地兼容使用。

### 下一阶段入口

建议进入 V2-03：统一文件理解、Markdown 支持、文件角色与关系候选、用户确认修正，并为后续异步任务计划建立稳定输入。

## V2-03：统一文件理解、Markdown、文件关系与用户确认

### 阶段编号

`V2-03`

### 实施内容

- 新增 `20260723_0004` 迁移和 `file_profiles`、`file_relations`、
  `file_processing_runs`。
- 增量扩展 `file_chunks`，在同一张表支持 PDF 页码分块和 Markdown 标题路径分块。
- 建立同步但可迁移到队列的统一文件理解服务，支持 CSV、所有 XLSX 工作表、
  PDF、PNG/JPG/JPEG/WEBP、MD/MARKDOWN。
- 新增确定性结构、统计、摘要、质量问题、角色和标签；DeepSeek 只做可选语义增强，
  严格 Schema 失败时降级。
- 用户确认角色和用户标签继续以 `workspace_files` 为真源，重新理解不覆盖。
- 新增表格字段、文档规则、图片 OCR、文件名时间/版本的关系候选，
  支持去重、确认、拒绝、修正和审计链。
- 新增 `context_version=2.03` 的 Workspace Context，只输出安全元数据和压缩结构。
- 上传增加扩展名、MIME、文件头、内容可读性、XLSX 压缩、PDF 页数、
  图片像素、大小、批量、工作区数量和用户总存储配额。
- 工作区前端增加批量上传、Profile、角色/标签、关系列表和 Context 预览。

### 主要修改文件

- `backend/alembic/versions/20260723_0004_v2_file_understanding.py`
- `backend/app/models/file_profile.py`
- `backend/app/models/file_relation.py`
- `backend/app/models/file_processing_run.py`
- `backend/app/services/file_understanding_service.py`
- `backend/app/services/file_relation_service.py`
- `backend/app/services/workspace_context_service.py`
- `backend/app/api/v2/file_understanding.py`
- `backend/app/api/v2/workspace_files.py`
- `backend/tests/test_v2_file_understanding.py`
- `backend/tests/test_v2_relations_context.py`
- `backend/tests/test_v2_file_api_security.py`
- `frontend/src/components/WorkspaceUnderstanding.jsx`
- `frontend/src/components/BatchFileUploader.jsx`
- `docs/V2_03_FILE_UNDERSTANDING.md`
- `docs/V2_03_MANUAL_ACCEPTANCE.md`

### 验证结果

- 后端全量：`48 passed`。
- Alembic head：`20260723_0004`。
- 临时 SQLite 已覆盖从零升级、回退到 `20260723_0003`、再次升级到 head。
- 前端 `npm run build`：成功，64 个模块完成生产构建。
- 真实开发数据库只执行只读 `current`，本阶段没有自动升级。
- 测试环境关闭 LLM，不读取真实 `.env`，不调用真实 DeepSeek。

### 已知限制

- 文件理解仍在同步 HTTP 请求中执行。
- 扫描 PDF 只提示需要 OCR，没有 PDF 页图 OCR。
- OCR 依赖 Tesseract 和语言包；成功文本仍需人工核对。
- CSV/Excel 的高成本统计使用受限样本，Profile 不保存全量数据。
- 关系置信度是可解释启发式阈值，不是真实概率；自动结果始终是候选。
- Workspace Context 不执行 Supervisor。
- 前端完成操作闭环但不是最终视觉稿。

### 下一阶段入口

建议进入 V2-04：计划草稿与用户确认、持久化队列、SSE、取消和受限局部重试。
在可靠执行层完成后，再实施 Supervisor 和专业子 Agent。

## V2-04：可靠任务执行层、计划确认与多 Agent 主体架构

### 阶段编号

`V2-04`

### 实施内容

- 新增 `20260724_0005` 增量迁移、五张任务执行表和 tasks 队列/进度/租约字段；
- 新增统一任务状态机、只追加事件、数据库队列、独立单 Worker、租约与心跳；
- 新增协作式取消、失败步骤及下游局部重试、Quality Review 最多一次自动重试；
- 新增草稿、主动追问、版本化计划、可视化修改、重新生成和确认 API；
- 新增 SSE、Last-Event-ID、增量轮询和前端自动降级；
- 新增版本化 AgentState、Supervisor、五个专业 Agent、Tool Registry 和 Prompt Registry；
- 新增多工作表预设 Pandas 分析、PDF/Markdown 证据、幂等 Markdown 报告和确定性质量审核；
- 新增工作区前端任务闭环与 Docker Compose worker 服务。

### 主要文件

- `backend/alembic/versions/20260724_0005_v2_reliable_task_execution.py`
- `backend/app/models/task_*.py`
- `backend/app/models/agent_run.py`
- `backend/app/services/task_state_machine.py`
- `backend/app/services/task_planning_service.py`
- `backend/app/services/task_queue_service.py`
- `backend/app/services/task_event_service.py`
- `backend/app/agents/supervisor.py`
- `backend/app/agents/specialists.py`
- `backend/app/agents/tool_registry.py`
- `backend/app/agents/v2_state.py`
- `backend/app/workers/task_worker.py`
- `frontend/src/components/TaskExecutionFlow.jsx`
- `docs/V2_04_RELIABLE_MULTI_AGENT.md`
- `docs/V2_04_MANUAL_ACCEPTANCE.md`

### 验证结果

- 后端全量测试：`62 passed, 1262 warnings in 50.49s`；测试使用独立临时目录，未调用真实 DeepSeek；
- Alembic head：`20260724_0005`；真实开发库只读 `current` 为 `20260723_0004`，未自动升级；
- 独立临时 SQLite 完成 `从零 upgrade head → downgrade 20260723_0004 → 再次 upgrade head`，最终回到 `20260724_0005`；
- 前端生产构建：Vite `64 modules transformed`，`npm run build` 成功；
- `docker compose config --quiet` 返回 0；当前环境仅提示用户目录下 Docker 客户端配置不可读，不影响 Compose 配置解析；
- `git diff --check` 返回 0，仅有 Git 的 LF/CRLF 工作区提示。

### 当前限制

- 单机单 Worker 和 SQLite，只面向五人以内低并发；
- 文件理解 API 本身仍同步；
- 不支持单次不可中断库调用的强制终止；
- 报告尚未拆成独立 `reports/report_assets` 版本模型；
- 未实现 Word/PDF 新导出、对象存储、PostgreSQL、专业队列和生产部署。

### 下一阶段入口

建议 V2-05 实施报告/资产版本、任务与模型配额、Worker 指标、管理端可观测、评估集和生产安全门禁。

## V2-05：报告交付、治理、评估、监控与生产安全

### 阶段编号

`V2-05`

### 已实施

- 新增 `20260724_0006` 增量迁移，不修改既有迁移；
- 新增报告、报告资产、反馈、Prompt 版本、配额/用量、模型调用、评估、清理和 Worker 状态模型；
- 任务完成生成初始报告，新模板或纠正生成递增版本，旧版本保留；
- 新增 Markdown、DOCX、PDF 幂等导出和鉴权下载；
- 新增扫描 PDF 低文本页 OCR 和页码级 `scanned_pdf_ocr` 分块；
- 新增反馈、报告重新生成、个人使用量和管理员治理 API；
- 新增 Prompt 激活安全校验和 `agent_runs` 版本关联；
- 新增服务端配额检查、Worker/Agent/工具/模型指标及三层健康检查；
- 新增 85 条公开合成评估集、deterministic CLI 和失败案例导出；
- 新增清理 CLI/管理员 dry-run、SQLite 备份/校验/保护性恢复；
- 新增 production 配置门禁、安全响应头、Docker OCR/PDF 字体依赖；
- 新增报告中心、反馈、使用量和管理员运行治理前端。

### 数据和隐私边界

- 管理员接口默认不返回普通用户报告正文、原始文件或未脱敏模型输入；
- storage key 不以 API 暴露，下载逐级校验所有权；
- 评估资源全部是项目内合成样例，deterministic 不调用 DeepSeek；
- 清理默认 dry-run，不按时间静默删除活跃用户文件和当前报告；
- 真实 `app.db` 未由实施过程自动升级。

### 验证记录

- 后端全量：`73 passed, 1708 warnings in 64.53s`。测试环境关闭真实 LLM/OCR，不读取真实用户内容。
- Alembic head：`20260724_0006`。独立临时 SQLite 完成从零 `upgrade head → downgrade 20260724_0005 → upgrade head`，最终为 `20260724_0006`。
- 真实开发数据库最终 revision：`20260724_0005`，仍需要由负责人备份后手动升级。验证期间曾误用 `DATABASE_URL`（Alembic 实际只接受 `ALEMBIC_DATABASE_URL`），导致真实库短暂升到 `0006`；发现后立即按已确认的原 revision 降回 `0005`，随后重新用独立临时库完成验证。
- deterministic 评估：85 条，`task_success_rate=1.0`、平均响应 1ms、P95 1ms、平均模型调用 0、平均工具调用 1.65。这里的 1.0 是确定性规则与预期路由自检结果，不代表真实模型准确率。
- 前端：`npm run build` 成功，Vite `68 modules transformed`。
- `docker compose config --quiet` 返回 0；仅出现当前用户 Docker 客户端配置不可读警告，不影响 Compose 配置解析。
- `git diff --check` 返回 0；仅有 Git 的 LF/CRLF 工作区提示。
- DOCX 使用 `python-docx` 完成结构与生成验证；当前机器缺少 LibreOffice，未完成 DOCX 页面渲染。PDF 已使用 Poppler 渲染并人工检查，无裁切或中文缺字。

### 下一阶段入口

进入 UI 美化阶段：重点优化报告版本导航、长报告阅读、图表/表格资产预览、配额提示、管理员监控信息密度、移动端和无障碍。数据库与对象存储迁移仍应作为独立生产化项目。

## V2-06：全站 UI、交互、响应式与可访问性重设计

### 阶段编号

`V2-06`

### 已实施

- 新增集中设计 Token，统一浅色、深色和跟随系统主题；
- 新增公共表单、按钮、状态、反馈、Dialog、Drawer、Stepper、Pagination 等组件；
- 新增全局 Toast、确认机制、错误边界和安全 Markdown 渲染；
- 全局布局改为桌面可折叠侧栏、顶部上下文栏和移动抽屉；
- 认证页补齐密码显示、实时校验、防重复提交和可访问 label；
- 工作区详情拆为概览、文件、关系、Context、新建分析、任务、报告和设置子路由；
- 重构批量上传、文件筛选、Profile、关系确认、任务计划和执行时间线；
- SSE 保持优先，补齐连接状态、事件去重、数量上限、轮询降级和终态清理；
- 报告中心新增安全结构化正文、目录、版本、资产预览、鉴权下载和反馈流程；
- 重构使用量和管理员治理信息架构，一次性秘密关闭后清除；
- 补齐 360px、768px、1024px、1440px 响应式基线和基础键盘/屏幕阅读器支持；
- 增加 10 项纯逻辑测试，没有引入新的 npm 依赖；
- 新增 `V2_06_UI_UX_SYSTEM.md` 和 `V2_06_MANUAL_ACCEPTANCE.md`。

### 安全和兼容边界

- 没有修改后端核心业务、Schema、数据库迁移或真实 `.env`；
- 没有改变 Cookie Session、CSRF、权限、队列、SSE 和下载鉴权；
- 不把 Token、密码、邀请码或任务真相写入浏览器持久存储；
- 没有使用远程字体、国外 CDN、外部图片或不安全 HTML；
- deterministic 评估始终标注为规则自检，不描述为真实模型准确率。

### 验证记录

- 前端纯逻辑：`npm test`，`10 passed`；
- 前端生产构建：`npm run build` 成功，Vite `77 modules transformed`，无编译警告；
- 后端全量：`73 passed, 1708 warnings in 26.87s`。首次运行在全部用例执行后因 Windows 系统临时目录清理权限返回 1，改用工作区 `--basetemp` 重跑后正式返回 0；
- 真实浏览器抽查：登录页桌面、360px 移动端、768px 深色主题和键盘焦点；
- 需要认证数据的页面仍需按 `V2_06_MANUAL_ACCEPTANCE.md` 完整人工验收；
- `docker compose config --quiet` 返回 0；只有当前用户 Docker 客户端配置不可读警告，不影响 Compose 配置解析；
- `git diff --check` 返回 0；只有 Git 的 LF/CRLF 工作区提示。

### 当前限制与下一入口

- 大型事件列表采用最近 300 条上限，没有引入虚拟列表依赖；
- 长报告按结构块安全渲染，没有引入重型富文本或虚拟化框架；
- 列表只展示当前 API 返回字段，不伪造最近状态、模板、降级或质量摘要；
- 下一阶段应进入国内同域部署适配：反向代理 `/api`、SSE 关闭缓冲、HTTPS Cookie/CSRF、持久数据库与对象存储；本阶段没有执行云部署、域名或 DNS 操作。

## V2-07：中国内地单机生产部署包、运维脚本与上线文档

### 阶段编号

`V2-07`

### 已实施

- 新增 `docker-compose.prod.yml`，包含 Nginx web、单进程 backend 和独立单 worker；
- 前端改为开发/构建/生产多阶段 Dockerfile，生产关闭 source map 并由 Nginx 托管；
- Nginx 增加同域 HTTPS、HTTP 跳转、SPA fallback、静态缓存、gzip、安全头、上传限制和 SSE 无缓冲；
- 后端镜像安装 Tesseract 中英文、Poppler、Noto CJK 和 PDF/图片基础库，以 UID 10001 非 root 运行；
- SQLite 增加 WAL、busy timeout、外键、连接 pre-ping/recycle，生产固定单 API/单 Worker；
- 新增精确代理白名单、绝对持久化路径、占位密钥、Legacy V1、Secure Cookie 等生产门禁；
- DeepSeek Base、Key、模型支持专用环境变量，旧模型名只触发 degraded，不冒充成功；
- 新增安全密钥生成、首次部署、离线镜像加载、备份、清理、健康检查、升级、代码回滚、完整恢复回滚和证书 reload 脚本；
- 新增 systemd timer 与 logrotate 示例；
- 新增五份 V2-07 部署/安全/备案 HTTPS/运维/验收文档并更新 README 和部署入口。

### 安全和数据边界

- 没有修改真实 `.env`、真实数据库、DNS 或证书；
- 没有连接云服务器、购买资源、提交备案或执行公网访问测试；
- 升级先备份再停写迁移；回滚不默认删除数据库，不承诺任意 Alembic downgrade 无损；
- 备份包含数据库、storage、manifest 和 SHA-256，不包含 `.env`、证书和密钥；
- 清理默认 dry-run，自动 apply 需要双重显式确认。

### 验证记录

- 后端全量：`90 passed, 1708 warnings in 29.09s`，使用工作区 `--basetemp` 后退出码 0；警告为既有弃用和解析提示。
- 新增部署静态/门禁测试 17 项，覆盖生产配置、旧模型降级、弱密码、Compose 隔离/持久化、Nginx SSE/SPA、镜像数据排除、回滚/清理安全和 Git 忽略。
- 前端：`npm test` 为 10 passed；`npm run build` 成功，77 modules transformed；未生成 source map。
- 本地与生产 Compose 均 `config --quiet` 返回 0；隔离 smoke Compose 在缺少验证密钥时按预期返回 1，提供临时验证密钥后返回 0。
- 所有 `deploy/scripts/*.sh` 通过 Linux `bash -n`。
- Docker Engine 29.6.1 可用；前端 Node build stage 在容器内实际完成 `npm ci` 和 Vite build。
- 完整 production backend/web 构建在获取 Docker Hub 官方 Python/Nginx 基础镜像鉴权 token 时因 IPv6 连接超时失败，未进入 Dockerfile 指令；本机没有这两个精确缓存镜像。因此未启动隔离生产容器，未实际验证容器 health/readiness/HTTPS/SSE 运行态。
- 未调用真实 DeepSeek，未连接服务器，未执行备案、DNS、真实证书或中国内地网络测试。
