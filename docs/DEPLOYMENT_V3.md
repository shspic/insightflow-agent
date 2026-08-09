# InsightFlow Agent 低成本部署指南（V3）

> 本文档是部署**说明**。当前项目**未**部署到任何公网平台，也未声称已部署；
> 未经授权不创建云资源、不发布公网服务。部署前请按本指南逐项确认。

## 1. 部署形态选择

| 方案 | 前端 | 后端 | 适合 |
| --- | --- | --- | --- |
| A. 单机 Docker（推荐） | Nginx 容器（生产镜像） | backend + worker 容器，`docker-compose.prod.yml` | 有 VPS/云主机的国内部署 |
| B. Vercel + Render/Railway/Fly.io | Vercel 静态托管 | Render/Railway/Fly.io 单容器 | 低成本海外演示 |
| C. 纯本地/内网 | `npm run build` + 任意静态服务 | uvicorn + worker | 简历演示、离线演示 |

- Render / Railway / Fly.io 均可直接跑 `backend/Dockerfile` 的容器（含 entrypoint 迁移）。
- Vercel 部署前端：`frontend/` 作为 Vite 项目，构建命令 `npm run build`，输出 `dist/`；
  API 地址通过 `VITE_API_BASE_URL` 构建期注入（见第 6 节），**不把密钥注入前端**。

## 2. SQLite 与持久化要求

| 目录 | 内容 | 持久化要求 |
| --- | --- | --- |
| `<root>/data` | `insightflow.db`（SQLite 主库） | **必须持久盘**：VPS 本地盘、Render 磁盘、Fly.io Volume、Railway 持久卷 |
| `<root>/storage/uploads` | 用户上传文件 | 持久盘（删除即丢文件） |
| `<root>/storage/reports` | 生成的报告（md/pdf） | 持久盘 |
| `<root>/storage/retrieval` | 检索索引 | 可重建（`rebuild_index`），但建议持久化避免重启后重建耗时 |
| `<root>/storage/charts` | 图表 | 可重建 |
| `<root>/backups` | 备份 | 持久盘 + 定期外置 |

- SQLite 单文件：免费平台休眠/重启不影响文件，但**并发写有限**（WAL + busy timeout 已配置）；
  单用户/低频 demo 完全够用；多用户高频生产建议迁移 PostgreSQL（不在当前范围）。
- 免费平台注意：Render 免费实例 512MB 内存 + 磁盘不持久（Free 实例重启丢盘）；
  Fly.io 免费额度含 3GB volume；Railway 有持久卷（计费）。选择方案 B 时确认磁盘持久化选项。

## 3. HTTPS / CORS / Cookie / CSRF

- 单机 Docker（方案 A）：Nginx 容器终止 TLS（`deploy/nginx/`，certbot 部署钩子在 `deploy/scripts/`）。
- 方案 B：Vercel 自动 HTTPS；后端平台自带 HTTPS 域名。
- `CORS_ORIGINS`：只填前端真实来源（如 `https://xxx.vercel.app`），生产禁止 `*` + credentials。
- Cookie：`AUTH_COOKIE_SECURE=true`、`AUTH_COOKIE_SAMESITE=lax`；CSRF 双 Token 头校验默认开启。
- 反代（Nginx）必须设置 `X-Forwarded-Proto/Host/For`，后端 `TRUST_PROXY_HEADERS=true` + `TRUSTED_PROXY_IPS` 限定来源，否则 HTTPS 判定与限流按错来源计算。

## 4. 环境变量清单

完整清单见 `deploy/.env.production.example`（全部占位符）。关键项：

| 变量 | 说明 | 必须 |
| --- | --- | --- |
| `AUTH_SECRET_KEY` | 高熵随机密钥（会话/CSRF 签名） | 是 |
| `DATABASE_URL` / `ALEMBIC_DATABASE_URL` | 指向持久盘 SQLite | 是 |
| `UPLOAD_DIR` / `REPORT_DIR` / `CHART_DIR` / `BACKUP_DIR` | 持久化目录 | 是 |
| `CORS_ORIGINS` / `PUBLIC_SITE_URL` | 前端真实来源 | 是 |
| `LLM_ENABLED=true` + `DEEPSEEK_API_KEY` + `DEEPSEEK_MODEL` | DeepSeek 生产配置 | 按需 |
| `TESSERACT_CMD` / `OCR_LANG` | OCR 配置（容器内 tesseract 已装） | 默认即可 |
| `AUTH_COOKIE_SECURE` / `TRUST_PROXY_HEADERS` | 见第 3 节 | 是 |

**密钥边界**：`.env` 不进 Git（`.gitignore` 已排除）；容器只从环境变量读 API Key；
CI 中不写真实 Key，使用 GitHub Secrets 占位（见 CI 工作流注释）。

## 5. DeepSeek / BGE / MCP 生产配置

- **DeepSeek**：`DEEPSEEK_API_KEY` + `DEEPSEEK_MODEL`（如 `deepseek-v4-flash`）。LLM 仅用于 Verification 规划；pipeline/规则/质量门全部确定性。
- **BGE**：容器**不自动下载模型**。生产需要 embedding 时：
  1. 构建期或部署后把模型缓存放入 `backend/data/model_cache`（挂载为 volume）；
  2. 或首次启动后由 `LocalEmbeddingProvider` 从 HuggingFace 下载（需要公网，超时按环境配置）；
  3. 离线部署：在构建机先下载模型，随镜像/挂载带入。
- **MCP**：Review Tools MCP Server 以独立 `mcp` 容器运行（`docker-compose.prod.yml`，复用 backend 镜像）；
  backend 经 Docker 内网 `http://mcp:8765/mcp` 访问，`8765` 不发布到宿主机（无 `ports`）；
  `ENGINEERING_MCP_INTERNAL_TOKEN` 必须配置高熵密钥（`generate_secrets.py` 生成，与 `AUTH_SECRET_KEY` 独立且不同），
  capability token 由服务端签发，不对外暴露；
  `ENGINEERING_MCP_ALLOW_CONTAINER_BIND=true` 仅生产 mcp 容器显式启用容器内部绑定（默认关闭，只允许 localhost）。

## 5b. 大陆公众站合规配置（阶段 6D-2）

- **公开上线门禁**：`PUBLIC_LAUNCH_ENABLED=true` 时，部署门禁（`validate_production_security`）
  要求以下必填项完整且不使用 `replace_` 占位符：
  `SITE_OPERATOR_NAME`、`SITE_CONTACT_EMAIL`、`ICP_FILING_NUMBER`、
  `PRIVACY_POLICY_VERSION`、`TERMS_VERSION`、`AI_MODEL_DISPLAY_NAME`、`AI_ASSISTED_NOTICE`；
  ICP 备案号格式校验（省简称+ICP备+编号），ICP 链接必须指向 `https://beian.miit.gov.cn/`
  （《非经营性互联网信息服务备案管理办法》第十三条）。
- **公安联网备案**：`PUBLIC_SECURITY_FILING_NUMBER` 允许留空，页脚显示
  "公安联网备案办理中（法定办理期限内）"明确状态；填写则校验格式
  （省简称+公网安备+编号+号），链接指向 `http://www.beian.gov.cn/portal/index.do`。
- **AI 标识**：`AI_ASSISTED_NOTICE`（默认"AI 辅助生成，须人工复核"）用于智能核验页、
  报告页与全站页脚；Markdown/PDF 报告包含可见 AI 辅助生成声明（不承诺结果完全准确，
  候选证据须人工确认）。`AI_MODEL_FILING_NUMBER`（生成式 AI 服务备案号）可留空=办理中。
  依据《人工智能生成合成内容标识办法》（国信办通字〔2025〕2 号）。
- **private/prelaunch 模式**（`PUBLIC_LAUNCH_ENABLED=false`）：全部公开字段允许为空，
  前端不显示运营与备案信息；AI 提示与法律页面模板始终可用。
- 本配置不构成完整法律合规意见；备案号须在工信部/公安备案平台真实办理后填写。

## 6. 前端 API 地址配置

- 构建期注入：`VITE_API_BASE_URL=https://api.example.com`（`frontend/Dockerfile` 的 build ARG）；
- 单机 Docker：生产镜像 `VITE_API_BASE_URL=""`（同域 Nginx 反代 `/api/`，无跨域）；
- Vercel 等跨域部署：`VITE_API_BASE_URL` 指向后端平台域名 + 后端 `CORS_ORIGINS` 对齐。

## 7. 数据备份与恢复

- `deploy/scripts/backup.sh`：SQLite（`sqlite3 .backup` 或文件拷贝）+ 目录打包，保留 `BACKUP_RETENTION_DAYS`；
- 恢复：停止写、还原备份文件与目录、`alembic upgrade head`（或 `python -m app.db.init_db`）校验 revision；
- 健康检查：`GET /api/health`；Nginx `nginx -t`；worker 有独立 healthcheck；
  MCP 容器有真实工具发现 healthcheck（`app.mcp.healthcheck`，不使用真实用户 token）；
  backend readiness（`/api/health/ready`）在 MCP 启用时报告 MCP 状态，MCP 故障时降级为 `degraded` 而非 `ready`。

## 8. 健康检查与回滚

- backend healthcheck：`urllib.request.urlopen('http://127.0.0.1:8000/api/health')`（compose 已配置 interval/retries/start_period）；
- 回滚：镜像 tag 固定版本（如 `insightflow-backend:2026-08-09`），`docker compose up -d` 换 tag 即回滚；
  SQLite 迁移向前兼容（0013→0014 仅加可空列，历史数据不改写），必要时先备份再升级。

## 9. 免费平台限制提醒

- Render 免费：实例休眠（无请求 15 分钟），磁盘不持久 → 数据需外置（Supabase/Neon 等）或升级付费；
- Railway：有试用额度，持久卷计费，构建需拉取 torch 依赖体积较大；
- Fly.io：免费额度含 3GB volume，注意机器休眠后冷启动耗时；
- Vercel：免费额度充足，注意函数超时与 SSE（本项目 SSE 由后端平台提供，前端只是 EventSource 客户端）。

## 10. 未验证内容

- 未在任何云平台真实部署（Vercel/Render/Railway/Fly.io）——本文档为说明，非部署记录；
- 未购买域名/证书/备案。
