# 部署与本地三进程启动

> V2-04：可靠任务执行必须同时运行 FastAPI API 和独立 Worker。数据库队列使用 SQLite 租约，不要求 Redis。当前只适合单机低并发；Vercel + Render 旧演示没有持久 Worker 和共享持久磁盘，不能宣称支持 V2-04 可靠任务恢复。

## V2-04 本地启动

首次升级前先停止写入并备份 `backend/data/app.db`，然后人工执行：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\alembic.exe -c alembic.ini current
.\.venv\Scripts\alembic.exe -c alembic.ini heads
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
```

终端一，API：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\activate
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

终端二，Worker：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\activate
python -m app.workers.task_worker
```

终端三，前端：

```powershell
cd D:\spir\NO2_agent\frontend
npm run dev
```

Worker 必须和 API 共享同一 `DATABASE_URL`、`UPLOAD_DIR`、`CHART_DIR` 和 `REPORT_DIR`。反向代理需关闭 SSE 缓冲并设置足够的空闲超时。

## V2-04 Docker Compose

根目录的 Compose 包含 `backend`、`worker`、`frontend`：

```powershell
docker compose config --quiet
docker compose up --build
```

Compose 不自动替代生产数据库备份流程。真实数据库迁移仍应由负责人在停写、备份和检查 revision 后人工执行。

关键环境变量：

```text
WORKER_POLL_INTERVAL_SECONDS=2
WORKER_LEASE_SECONDS=120
WORKER_HEARTBEAT_SECONDS=15
TASK_MAX_RETRIES=1
AGENT_MAX_REPLAN_COUNT=1
AGENT_MAX_REVIEW_RETRIES=1
TASK_MAX_CLARIFICATION_ROUNDS=2
TASK_EVENT_HEARTBEAT_SECONDS=15
```

## 旧版免费公网部署准备

> V2-03 提示：本文主体记录的是旧版 Vercel + Render 演示方案，不是 V2 最终生产推荐。V2 使用 Cookie Session，推荐同一域名提供前端并将 `/api` 反向代理到 FastAPI；生产环境必须配置高熵 `AUTH_SECRET_KEY`、`AUTH_COOKIE_SECURE=true`、`ENABLE_LEGACY_V1_API=false`，并使用持久数据库和持久文件存储。跨站部署还需逐项验证 SameSite、CORS 和第三方 Cookie 限制。V2-03 还必须按 [V2-03 文件理解文档](V2_03_FILE_UNDERSTANDING.md)配置上传安全、配额、关系阈值和上下文上限。

本文档说明如何把 InsightFlow Agent 按前后端分离方式部署到免费公网环境：

- 前端：Vercel。
- 后端：Render。
- 前端通过 `VITE_API_BASE_URL` 访问 Render 后端。
- 后端通过 `CORS_ORIGINS` 允许 Vercel 前端跨域访问。

## 1. 部署方案说明

推荐结构：

```text
Vercel React 前端
  ↓ VITE_API_BASE_URL
Render FastAPI 后端
  ↓
SQLite + Render 本地临时文件系统
```

当前方案适合演示和面试展示，不适合作为生产级长期存储方案。Render 免费 Web Service 的本地文件系统和 SQLite 数据不应被视为长期可靠存储。

## 2. GitHub 仓库准备

部署前先确认：

1. 已把项目推送到 GitHub。
2. `backend/.env` 没有提交。
3. `backend/data/`、`backend/storage/`、`frontend/node_modules/` 没有提交。
4. `backend/.env.example` 只包含占位符。
5. README 中没有真实 API Key、本机隐私路径或虚假部署地址。

## 3. Render 后端部署步骤

方式一：使用 `render.yaml`。

1. 在 Render 新建 Blueprint。
2. 选择当前 GitHub 仓库。
3. Render 会读取项目根目录的 `render.yaml`。
4. 创建服务后，在 Render 控制台补充真实环境变量，例如 `LLM_API_KEY`。
5. 把 `CORS_ORIGINS` 改成真实 Vercel 前端地址。

方式二：手动创建 Web Service。

1. 在 Render 创建 `Web Service`。
2. 连接 GitHub 仓库。
3. Root Directory 填写：

```text
backend
```

4. Build Command 填写：

```bash
pip install -r requirements.txt
```

5. Start Command 填写：

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

6. Health Check Path 填写：

```text
/api/health
```

## 4. Vercel 前端部署步骤

1. 在 Vercel 新建项目。
2. 选择当前 GitHub 仓库。
3. Root Directory 选择：

```text
frontend
```

4. Build Command 使用默认或填写：

```bash
npm run build
```

5. Output Directory 使用：

```text
dist
```

6. 在 Vercel 环境变量中设置：

```text
VITE_API_BASE_URL=https://你的-render-后端地址.onrender.com
```

不要在前端代码中写死 Render 地址。

## 5. 环境变量配置

### Render 后端环境变量

```text
APP_NAME=InsightFlow Agent
ENV=production
DATABASE_URL=sqlite:///./data/app.db
UPLOAD_DIR=./storage/uploads
CHART_DIR=./storage/charts
REPORT_DIR=./storage/reports
CORS_ORIGINS=https://你的-vercel-前端地址.vercel.app
LLM_ENABLED=true
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_BASE_URL=
LLM_API_KEY=你的真实 Key，只在 Render 环境变量中填写
RAG_RETRIEVAL_MODE=auto
RAG_TOP_K=5
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=100
TESSERACT_CMD=
OCR_LANG=chi_sim+eng
UPLOAD_MAX_FILE_SIZE_BYTES=20971520
UPLOAD_MAX_BATCH_FILES=10
WORKSPACE_MAX_FILES=50
USER_STORAGE_QUOTA_BYTES=209715200
RELATION_MIN_CONFIDENCE=0.60
RELATION_HIGH_CONFIDENCE=0.80
RELATION_MAX_PAIRS=100
WORKSPACE_CONTEXT_MAX_FILES=20
WORKSPACE_CONTEXT_MAX_CHARS=30000
```

说明：

- 不要把真实 `LLM_API_KEY` 写入 README、`render.yaml` 或代码。
- `TESSERACT_CMD` 在 Render 上通常留空。
- 如果没有配置 LLM Key，系统会回退到本地规则和模板逻辑。
- 管理员只绕过普通用户总存储配额，仍受单文件、批量、格式、页数和像素安全上限约束。
- 免费临时磁盘不适合保存用户上传文件、Profile、关系和审计记录；正式环境必须采用持久存储并建立备份。

### Vercel 前端环境变量

```text
VITE_API_BASE_URL=https://你的-render-后端地址.onrender.com
```

本地开发时可以不设置该变量，前端会默认访问：

```text
http://localhost:8000
```

## 6. CORS 配置

Render 后端需要允许 Vercel 前端域名跨域访问。

单个前端地址示例：

```text
CORS_ORIGINS=https://你的-vercel-前端地址.vercel.app
```

同时允许本地开发和 Vercel：

```text
CORS_ORIGINS=https://你的-vercel-前端地址.vercel.app,http://localhost:5173
```

多个地址用英文逗号分隔，不要使用空格。

## 7. 部署后验证地址

替换为真实 Render 地址后验证：

```text
https://你的-render-后端地址.onrender.com/api/health
https://你的-render-后端地址.onrender.com/docs
```

替换为真实 Vercel 地址后验证：

```text
https://你的-vercel-前端地址.vercel.app
```

建议验证流程：

1. 打开后端 `/api/health`，确认返回 `status: ok`。
2. 打开 Swagger，确认接口文档可访问。
3. 打开前端页面，确认文件列表请求不报 CORS 错误。
4. 上传一个小 CSV，验证上传、解析、分析是否可用。
5. 创建一个简单任务，确认执行轨迹能展示。

## 8. 常见问题

### 前端请求后端失败

优先检查：

1. Vercel 是否配置了 `VITE_API_BASE_URL`。
2. `VITE_API_BASE_URL` 是否包含 Render 后端完整域名。
3. Render 的 `CORS_ORIGINS` 是否包含 Vercel 前端域名。
4. 修改 Vercel 环境变量后是否重新部署前端。

### Render 后端启动失败

优先检查：

1. Root Directory 是否是 `backend`。
2. Start Command 是否使用 `$PORT`。
3. `requirements.txt` 是否安装成功。
4. Render 日志中是否有依赖安装错误。

### OCR 不可用

公网演示版不保证内置 Tesseract OCR。当前 OCR 服务会在缺少引擎或语言包时返回清晰中文提示，不应影响文件上传、表格分析、PDF RAG、任务系统和报告生成。

### 上传文件或数据库数据丢失

Render 免费 Web Service 的本地文件系统适合演示，不适合长期保存用户上传文件、SQLite 数据库、图表和报告。服务重建、迁移或休眠恢复后，数据可能不可长期依赖。

## 9. 免费部署限制

- Render 免费服务可能冷启动，首次访问会比较慢。
- SQLite 和本地 storage 只适合演示，不适合长期持久化。
- OCR 依赖部署环境是否安装 Tesseract。
- 大文件上传、长时间 PDF 处理和复杂图表生成可能受免费实例资源限制。
- 当前项目仍是单用户演示版，没有生产级认证、权限和配额控制。

## 10. 后续生产化升级方向

- SQLite 升级为 Postgres。
- 本地 `storage` 升级为对象存储，例如 S3、R2 或 OSS。
- OCR 改为独立服务或接入可控的 OCR / VLM API。
- 后端增加用户登录、权限管理和上传配额。
- 文件处理改为异步任务队列。
- RAG 检索升级为持久化向量数据库。
