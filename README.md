# InsightFlow Agent：多模态文档与数据分析智能体

## 项目简介

InsightFlow Agent 是一个基于 FastAPI + React + LangGraph 的多模态文档与数据分析 Agent 平台。项目支持 Excel、CSV、PDF、图片和 Markdown 文件上传，并通过统一文件理解、自然语言任务、PDF 检索问答、图片 OCR、图表生成、Markdown 报告生成和 Agent 执行轨迹展示完成分析工作。

这个项目的定位不是普通聊天机器人，而是一个围绕“文件输入、任务判断、工具调用、结果生成、过程可观测”构建的任务执行型 AI 应用。

## V2-08 当前状态（2.0.0-rc.1）

V2-08 已完成 V2-01 至 V2-07 全部阶段的最终回归验收：90 条后端测试、10 条前端测试、Alembic 完整迁移、deterministic 评估、代码/文档一致性审计、弃用警告治理、隔离验收环境和合成演示资料建设。代码主线已正式封板为 2.0.0-rc.1 发布候选版本。

已完成：多用户认证和工作区隔离、五类文件理解与关系确认、计划确认与任务队列、独立 Worker 与 SSE、Supervisor + 五个专业 Agent、三格式报告导出、配额/监控/评估/备份、全站 UI 和中国内地单机部署包。

尚未完成：未购买服务器、未备案、未配置公网 HTTPS、未执行真实 DeepSeek/OCR 验收、未迁移 PostgreSQL 和对象存储。

详细说明：

- [V2-08 最终发布](docs/V2_08_FINAL_RELEASE.md)
- [V2-08 最终验收](docs/V2_08_FINAL_ACCEPTANCE.md)
- [V2-08 已知限制](docs/V2_08_KNOWN_LIMITATIONS.md)
- [V2-08 演示指南](docs/V2_08_DEMO_GUIDE.md)
- [V2-08 安全检查](docs/V2_08_SECURITY_CHECKLIST.md)
- [变更日志](CHANGELOG.md)
- [V2-06 UI/UX 系统](docs/V2_06_UI_UX_SYSTEM.md)
- [V2-06 手动验收](docs/V2_06_MANUAL_ACCEPTANCE.md)
- [V2-07 中国内地部署](docs/V2_07_MAINLAND_DEPLOYMENT.md)
- [V2-07 服务器初始化](docs/V2_07_SERVER_SETUP.md)
- [V2-07 域名、备案与 HTTPS](docs/V2_07_DOMAIN_ICP_HTTPS.md)
- [V2-07 运维手册](docs/V2_07_OPERATIONS_RUNBOOK.md)
- [V2-07 上线验收](docs/V2_07_MANUAL_ACCEPTANCE.md)
- [V2-05 报告与治理](docs/V2_05_REPORTS_GOVERNANCE_EVALUATION.md)
- [V2-05 手动验收](docs/V2_05_MANUAL_ACCEPTANCE.md)
- [V2-05 评估指南](docs/V2_05_EVALUATION_GUIDE.md)
- [V2-05 备份恢复](docs/V2_05_BACKUP_AND_RECOVERY.md)
- [V2 产品架构计划](docs/V2_PRODUCT_AND_ARCHITECTURE_PLAN.md)
- [V2 实施日志](docs/V2_IMPLEMENTATION_LOG.md)

真实数据库升级前必须停写并备份，再手工执行：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe heads
.\.venv\Scripts\alembic.exe upgrade head
```

V2-04 当前状态说明保留如下，作为兼容基础。

## V2-04 兼容基础

当前代码已在 V2-03 文件理解基础上完成 V2-04 可靠任务执行层：自然语言任务草稿、最多两轮主动追问、版本化计划、可视化修改与确认、SQLite 持久化队列、独立单 Worker、租约与心跳、SSE/轮询恢复、协作式取消、受限局部重试，以及 Supervisor + File Understanding、Data Analysis、Document Research、Report、Quality Review 五个专业 Agent。计划确认前不会执行正式分析工具。

旧 `/api/files`、`/api/tasks`、`/api/reports` 仅为本地兼容保留，由 `ENABLE_LEGACY_V1_API` 控制。旧接口没有完整多用户隔离，正式公网环境必须设置为 `false`。

V2-03 的文件理解接口本身仍为同步调用；V2-04 新任务执行已进入独立 Worker。当前不支持任意节点暂停后原地恢复、Redis/Celery、PostgreSQL、对象存储或正式国内生产部署。Markdown/DOCX/PDF 版本化导出已在 V2-05 实现。

## 版本与公网状态

当前版本：**2.0.0-rc.1**（发布候选，2026-07-24），详见 [CHANGELOG.md](CHANGELOG.md)。

仓库不提供或承诺现成的 V2 公网地址。历史 Vercel/Render 演示地址（V1 时代）不属于 V2 生产路径，仅作为历史记录保留在部分旧文档中。真实上线必须由用户完成服务器购买、域名备案、DNS 配置、HTTPS 证书和手动验收。

## 核心功能

- 安全文件上传：支持 `.csv`、`.xlsx`、`.pdf`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.md`、`.markdown`，并校验扩展名、MIME、内容特征、大小和配额。
- 统一文件理解：为表格、PDF、图片和 Markdown 生成版本化 Profile，包括摘要、结构、统计、质量、角色、标签、解析器和降级信息。
- 文件关系：基于字段、标题、文件名、文档和 OCR 特征生成可解释候选，必须由用户确认后才视为事实。
- Workspace Context：按选中文件生成脱敏、裁剪、版本化的后续 Agent 输入。
- Excel / CSV 解析：覆盖所有工作表，提取字段、行列数、类型、样本、缺失值、重复行、数值统计、日期范围和标识列候选。
- 表格数据分析：基于 Pandas 生成字段类型、数值统计、文本高频值和缺失值统计。
- 图表生成：基于 Matplotlib 生成缺失值统计图、数值统计图和分类 Top 5 图。
- PDF RAG 检索问答：对 PDF 文本分块、检索，并生成带页码和引用片段的回答。
- 图片 OCR：使用 pytesseract + Pillow 识别图片文字，并保存 OCR 结果。
- 可靠任务执行：计划确认后进入数据库队列，由独立 Worker 通过租约认领并逐步骤持久化。
- 多 Agent：Supervisor 调度五个职责明确的专业 Agent；解析、OCR、Pandas、图表、检索和报告写入仍是注册工具。
- 实时进度：SSE 支持断线事件恢复，前端失败后自动降级增量轮询。
- 执行轨迹可视化：记录并展示每个 Agent 节点的输入、输出、状态、耗时和错误信息。
- LLM 可选增强：配置 API Key 后可增强任务理解、RAG 回答、最终回答和报告总结；未配置时自动降级到本地规则。
- Markdown 报告生成：基于任务、文件分析、图表、PDF 引用和 OCR 结果生成报告。
- Docker Compose 一键启动：本地可通过 `docker compose up --build` 同时启动前端和后端。

## 技术栈

- 前端：React、React Router、Vite、浏览器原生 `fetch`。
- 后端：FastAPI、Uvicorn、Pydantic。
- 数据库：SQLite、SQLAlchemy。
- 数据分析：Pandas、openpyxl。
- 图表：Matplotlib。
- PDF：PyMuPDF。
- OCR：pytesseract、Pillow、Tesseract OCR。
- Agent：LangGraph。
- 工程化：Docker、Docker Compose。

## 系统架构

```mermaid
flowchart TD
    A["React 前端"] --> B["FastAPI 后端"]
    B --> C["计划确认 / 数据库队列"]
    C --> W["独立 Worker / Supervisor"]
    W --> D["File Understanding Agent"]
    W --> E["Data Analysis Agent"]
    W --> G["Document Research Agent"]
    W --> I["Report Agent"]
    W --> Q["Quality Review Agent"]
    D --> J["SQLite + 本地文件存储"]
    E --> J
    G --> J
    I --> J
    Q --> J
```

## V2 Agent 工作流

```text
任务草稿 → 主动追问 → Supervisor 计划草稿 → 用户确认
→ 持久化队列 → Worker 租约认领 → 五个专业 Agent
→ Quality Review → 最多一次局部重试 → Markdown 报告
```

旧 V1 LangGraph 仅在 `ENABLE_LEGACY_V1_API=true` 时保留兼容。V2 Tool Registry 不允许任意 Python、Shell、SQL、URL、动态 import 或未注册工具。

## 项目目录结构

```text
NO2_agent/
  backend/
    app/
      agents/       # LangGraph Agent 节点、状态和执行入口
      api/          # FastAPI 路由
      core/         # 配置系统
      db/           # SQLAlchemy 会话和初始化脚本
      models/       # 数据库模型
      schemas/      # 请求 / 响应结构
      services/     # 文件、解析、分析、图表、RAG、OCR、报告服务
    Dockerfile
    requirements.txt
    .env.example
  frontend/
    src/
      api/          # 前端 API 请求封装
      components/   # 公共控件、布局、文件、任务、报告和管理组件
      context/      # 认证、主题和全局反馈
      pages/        # 认证、工作区、使用量和管理页面
      styles/       # 设计 Token
      utils/        # 状态、错误、SSE 和报告等纯逻辑
    Dockerfile
    package.json
  docs/
    PRD.md
    DEMO_SCRIPT.md
    DEPLOYMENT.md
    EVALUATION.md
    FINAL_CHECKLIST.md
    INTERVIEW_QA.md
    MCP_PLAN.md
    PROJECT_REVIEW.md
    RESUME.md
    SCREENSHOTS.md
    TESTING.md
  screenshots/
    .gitkeep
  examples/
    demo_workspace/   # 合成演示资料
  scripts/             # 验收和部署辅助脚本
  docker-compose.yml
  docker-compose.prod.yml
  README.md
  AGENTS.md
  CHANGELOG.md
  VERSION
```

## 本地开发启动方式

### 后端启动

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
python -m app.cli.create_admin
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Worker 启动

另开一个终端：

```powershell
cd backend
.venv\Scripts\activate
python -m app.workers.task_worker
```

后端默认地址：

```text
http://localhost:8000
```

### 前端启动

```powershell
cd frontend
npm install
npm run dev
```

前端默认地址：

```text
http://localhost:5173
```

## Docker Compose 启动方式

在项目根目录执行：

```powershell
cd <项目根目录>
docker compose up --build
```

访问地址：

- 前端：[http://localhost:5173](http://localhost:5173/)
- 后端：[http://localhost:8000](http://localhost:8000/)
- Swagger：[http://localhost:8000/docs](http://localhost:8000/docs)
- 健康检查：[http://localhost:8000/api/health](http://localhost:8000/api/health)

停止服务：

```powershell
docker compose down
```

Docker Compose 会把后端数据挂载到本地目录，便于重启后保留数据：

- `backend/data`：SQLite 数据库目录。
- `backend/storage/uploads`：上传文件目录。
- `backend/storage/charts`：图表图片目录。
- `backend/storage/reports`：Markdown 报告目录。

## 环境变量说明

- `backend/.env.example` 是配置模板，可以复制为 `backend/.env`。
- `backend/.env` 是真实本地配置，不应提交到 GitHub。
- `TESSERACT_CMD` 用于配置本机 Tesseract 可执行文件路径。
- `OCR_LANG` 用于配置 OCR 语言，例如 `chi_sim+eng`。
- `AUTH_SECRET_KEY` 必须使用至少 32 字符的独立高熵密钥；生产环境缺失时应用会拒绝启动。
- `AUTH_COOKIE_SECURE` 在本地 HTTP 可为 `false`，生产 HTTPS 必须为 `true`。
- `ENABLE_LEGACY_V1_API` 本地兼容阶段可为 `true`，正式公网必须为 `false`。
- `UPLOAD_MAX_FILE_SIZE_BYTES`、`UPLOAD_MAX_BATCH_FILES`、`WORKSPACE_MAX_FILES`、`USER_STORAGE_QUOTA_BYTES` 控制上传安全和配额。
- `RELATION_MIN_CONFIDENCE`、`RELATION_HIGH_CONFIDENCE`、`RELATION_MAX_PAIRS` 控制关系候选。
- `WORKSPACE_CONTEXT_MAX_FILES`、`WORKSPACE_CONTEXT_MAX_CHARS` 控制上下文裁剪。
- `WORKER_POLL_INTERVAL_SECONDS`、`WORKER_LEASE_SECONDS`、`WORKER_HEARTBEAT_SECONDS` 控制单 Worker 轮询、租约和心跳。
- `TASK_MAX_RETRIES`、`AGENT_MAX_REPLAN_COUNT`、`AGENT_MAX_REVIEW_RETRIES`、`TASK_MAX_CLARIFICATION_ROUNDS` 控制重试和循环上限。

V2-03 所有默认值和完整调整方式见 [docs/V2_03_FILE_UNDERSTANDING.md](docs/V2_03_FILE_UNDERSTANDING.md)；真实密钥只应写入部署环境或未提交的 `backend/.env`。

Windows 本机示例，请按实际安装位置填写：

```text
TESSERACT_CMD=<Tesseract 安装目录>/tesseract.exe
OCR_LANG=chi_sim+eng
```

当前后端镜像安装 Tesseract 中英文语言包、Poppler 和 Noto CJK 字体，支持图片/扫描 PDF OCR 与 PDF 中文导出。构建需要相应 Debian 软件源可用；也可以在可联网构建机生成镜像 tar 后传入服务器。

## 测试命令

后端轻量测试：

```powershell
cd backend
pytest
```

前端纯逻辑测试与构建：

```powershell
cd frontend
npm test
npm run build
```

完整测试说明见 [docs/TESTING.md](docs/TESTING.md)，项目评估方法见 [docs/EVALUATION.md](docs/EVALUATION.md)，最终发布检查清单见 [docs/FINAL_CHECKLIST.md](docs/FINAL_CHECKLIST.md)。

## 国内同域部署入口

V2 的低并发正式部署目标是同域名提供前端，反向代理将 `/api` 转发到 FastAPI。前端默认使用相对 `/api/v2`；`VITE_API_BASE_URL` 只作为兼容覆盖项。当前 Vercel + Render 组合仅用于旧版演示，不作为 V2 最终生产目标。

同域反向代理需要：

- 前端静态资源和 API 使用同一站点；
- `/api` 转发到 FastAPI，SSE 路径关闭代理缓冲并配置足够读超时；
- Cookie、CSRF、可信代理头和 HTTPS 安全选项按同域配置；
- 报告下载保留 `Content-Disposition` 和鉴权 Cookie；
- 不在业务组件写死 localhost、Vercel、Render 或外部 CDN。

生产 Compose 使用 `/srv/insightflow` 持久化数据库、storage、备份、日志和证书。完整部署步骤见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) 与 [V2-07 中国内地部署](docs/V2_07_MAINLAND_DEPLOYMENT.md)。不要把真实 DeepSeek Key 写入 README、代码或仓库文件。

## API 模块说明

- `/api/health`：健康检查接口。
- `/api/v2/auth`、`/api/v2/admin`、`/api/v2/workspaces`：认证、最小管理员后台和用户工作区。
- `/api/v2/workspaces/{workspace_id}/files`：工作区文件列表、单文件和批量上传。
- `/api/v2/workspaces/{workspace_id}/files/*/understand|profile`：单个/批量文件理解、Profile 查询和角色标签确认。
- `/api/v2/workspaces/{workspace_id}/file-relations`：关系发现、筛选、确认、拒绝和修正。
- `/api/v2/workspaces/{workspace_id}/context-preview`：生成脱敏的 Workspace Context 预览。
- `/api/v2/workspaces/{workspace_id}/tasks/drafts`：创建 V2 任务草稿并触发追问或计划。
- `/api/v2/workspaces/{workspace_id}/tasks/{task_id}/plans/*`：版本化修改、重新生成和确认计划。
- `/api/v2/workspaces/{workspace_id}/tasks/{task_id}/events/stream`：SSE 实时任务事件。
- `/api/v2/workspaces/{workspace_id}/tasks/{task_id}/cancel|retry`：取消和受限重试。
- `/api/files`：文件上传、文件列表、文件详情、解析、分析、图表、PDF 索引、PDF 检索、图片 OCR。
- `/api/tasks`：创建自然语言任务、查看任务列表、任务详情和执行轨迹。
- `/api/reports`：查看和下载 Markdown 报告。

## 功能演示流程

适合录屏或面试展示的流程：

1. 启动项目：执行 `docker compose up --build`，打开前端和 Swagger。
2. 管理员创建邀请码，注册普通用户并创建工作区。
3. 批量上传 CSV、XLSX、PDF、图片和 Markdown，检查逐文件验证状态。
4. 批量理解文件，查看摘要、结构、质量、建议角色、标签、解析器和降级信息。
5. 确认或修改角色和标签，重新理解后确认值仍被保留。
6. 发现文件关系，确认、拒绝并修正关系类型和备注。
7. 选择文件并查看 Workspace Context，确认仅包含安全元数据、角色、关系和质量问题。
8. 创建任务草稿，回答追问，修改并确认计划。
9. 启动 Worker，通过 SSE 查看五个 Agent 的步骤、工具摘要和进度。
10. 验证取消、失败步骤重试、Quality Review 和 Markdown 报告。
11. 使用第二个用户验证任务、事件、计划、报告和图表隔离。

完整步骤见 [docs/V2_04_MANUAL_ACCEPTANCE.md](docs/V2_04_MANUAL_ACCEPTANCE.md)。

## 项目截图

> 截图将在 `screenshots/` 目录中补充，包括首页、上传页、文件解析、数据分析、图表生成、Agent 任务执行、执行轨迹、PDF RAG、图片 OCR、Markdown 报告、Docker 启动、Swagger API 文档和 GitHub README 页面。

当前仓库只保留 `screenshots/.gitkeep` 作为目录占位，没有插入不存在的图片链接。详细截图清单见 [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md)。

## 项目亮点

- 不只是普通聊天机器人，而是面向文件和任务执行的多模态 Agent 应用。
- 覆盖文件解析、工具调用、LangGraph 工作流、执行轨迹、PDF RAG、图片 OCR、图表和报告生成。
- 前后端完整闭环，包含 FastAPI API、React 页面、SQLite 任务历史和本地文件存储。
- Agent 执行过程可观测，便于调试、展示和解释每一步工具调用。
- 支持 Docker Compose 一键启动，适合本地演示和面试讲解。
- 已整理 Vercel + Render 免费公网部署方案，适合快速给面试官打开演示。
- 适合 AI 应用开发、AI Agent 开发、后端工程和数据分析工具方向展示。

## 适合岗位

- AI 应用开发实习
- AI Agent 应用开发实习
- Python 后端开发实习
- RAG 应用开发实习
- 全栈 AI 应用开发实习
- 数据分析工具开发实习

## 当前限制

- 单机 SQLite + 单 Worker，适合 5 人以内低并发，不是生产级 SaaS。
- RAG 使用关键词和 TF-IDF 检索，不是生产级向量数据库方案。
- OCR 依赖本机或容器中的 Tesseract，中文识别需人工复核。
- 扫描 PDF OCR 受页数、像素、DPI 和超时限制。
- 文件理解接口仍为同步调用。
- 不支持任意节点暂停后原地恢复。
- 单机本地备份无法应对整盘损坏。
- 未执行真实 DeepSeek 质量评估（模型名使用占位符）。
- 未购买服务器/域名/备案/HTTPS。
- 未执行生产 Docker 容器构建和启动验证。
- deterministic 评估准确率 1.0 是规则自检，不代表 Agent 或模型真实准确率。

## 后续步骤

### 用户手动完成
1. 购买中国内地服务器、域名并完成 ICP 备案。
2. 配置 DNS、申请 HTTPS 证书，完成公网部署。
3. 核实 DeepSeek 可用模型名并配置生产 Key。
4. 执行真实 OCR、真实模型调用和中国内地多运营商网络验收。

### 可选独立项目
- PostgreSQL、对象存储和专业队列后端迁移。
- 语义 embedding 和持久化向量检索。
- 自动化浏览器 E2E 测试。
- CI/CD 和持续部署流水线。
