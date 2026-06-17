# InsightFlow Agent

InsightFlow Agent 是一个多模态文档与数据分析智能体项目，当前支持文件上传、CSV / Excel 分析、图表生成、PDF RAG、图片 OCR、LangGraph 任务工作流和 Markdown 报告生成。

## Docker Compose 本地一键启动

### 前置条件

- 已安装 Docker Desktop。
- 后端需要有 `backend/.env` 文件。可以从示例文件复制：

```bash
cd backend
copy .env.example .env
```

如果在 Windows PowerShell 中执行：

```powershell
Copy-Item .env.example .env
```

不要把真实 `.env` 提交到版本库。

### 一键启动

在项目根目录执行：

```bash
docker compose up --build
```

### 访问地址

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- Swagger：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

### 停止服务

```bash
docker compose down
```

### 数据目录说明

Docker Compose 会把后端数据挂载到本地目录，便于重启后保留数据：

- `backend/data`：SQLite 数据库目录。
- `backend/storage/uploads`：上传文件目录。
- `backend/storage/charts`：图表图片目录。
- `backend/storage/reports`：Markdown 报告目录。

### OCR 说明

Docker 演示版默认不内置 Tesseract OCR，目的是减少构建阶段对 Debian 软件源的依赖，优先保证前端和后端可以一键启动。

```text
TESSERACT_CMD=
OCR_LANG=chi_sim+eng
```

如果容器内未配置 OCR 引擎，图片 OCR 会返回明确提示：

```text
OCR 引擎未配置，请安装 Tesseract 或后续接入 VLM API。
```

这不会影响文件上传、表格分析、图表生成、PDF RAG、LangGraph 任务流和 Markdown 报告等主要功能。

如果后续需要在 Docker 中启用 OCR，可以基于 `backend/Dockerfile` 自行安装 Tesseract，并在容器环境中设置正确的 `TESSERACT_CMD` 和 `OCR_LANG`。

## 手动启动

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```
