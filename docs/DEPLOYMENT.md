# InsightFlow 部署入口

## 本地开发

本地仍使用 HTTP 和三进程，不启用生产 HTTPS 门禁：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m app.workers.task_worker
```

```powershell
cd D:\spir\NO2_agent\frontend
npm run dev
```

也可运行本地开发 Compose：

```powershell
cd D:\spir\NO2_agent
docker compose up --build
```

本地开发访问地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- Swagger：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/api/health`

以上地址是本地开发专用，不对外提供服务。

## V2-08 验收环境

V2-08 提供的隔离验收脚本使用独立 `.runtime/` 目录，包含临时数据库和临时 storage，不影响开发/生产数据：

```powershell
# 启动验收环境（后端 + Worker + 前端）
.\scripts\start_final_acceptance.ps1

# 停止验收环境
.\scripts\stop_final_acceptance.ps1

# 清理验收环境（删除临时数据库、storage 和日志）
.\scripts\clean_final_acceptance.ps1
```

验收环境自动创建管理员账号和演示工作区。详细说明见 `examples/demo_workspace/README.md`。

## V2-07 生产入口（当前主要部署方案）

V2 正式部署只采用中国内地 Linux 单机同域方案：

- `web`：Nginx + React 静态产物，发布 80/443；
- `backend`：单 Uvicorn 进程，只在内部网络提供 8000；
- `worker`：独立单 Worker；
- SQLite WAL 和 storage bind mount 到 `/srv/insightflow`；
- `/api` 同域反代，SSE 专用无缓冲配置；
- 正式环境强制 HTTPS Cookie、精确 CORS/代理白名单和 Legacy V1 关闭。

快速校验：

```bash
cp deploy/.env.production.example deploy/.env.production
# 人工替换全部占位符并放置证书后
docker compose --env-file deploy/.env.production \
  -f docker-compose.prod.yml config --quiet
sudo bash deploy/scripts/deploy.sh
```

完整文档：

- [总体生产部署](V2_07_MAINLAND_DEPLOYMENT.md)
- [Ubuntu 与安全加固](V2_07_SERVER_SETUP.md)
- [域名、备案、DNS 与 HTTPS](V2_07_DOMAIN_ICP_HTTPS.md)
- [日常运维、备份、升级与回滚](V2_07_OPERATIONS_RUNBOOK.md)
- [真实上线手动验收](V2_07_MANUAL_ACCEPTANCE.md)

## 历史演示环境（V1，非 V2 生产路径）

以下地址为 V1 单用户演示版的历史部署，不再作为 V2 正式生产路径：

- 前端（Vercel）：`https://insightflow-agent.vercel.app`
- 后端（Render）：`https://insightflow-agent-spi.onrender.com`
- 健康检查（Render）：`https://insightflow-agent-spi.onrender.com/api/health`

该部署存在已知限制：Render 免费服务冷启动慢、文件系统不持久、OCR 可能不可用、无用户认证和多租户隔离。V2 正式环境应从零按 V2-07 方案部署，不继承 V1 的 Vercel/Render 数据或配置。

## 明确边界

本节记录的是 V1/V2 阶段边界，不能代表当前部署状态。当前 `master` 对应 Git Tag `v3.0.2`，并已在 <https://43.153.181.237/> 完成单机 HTTPS 公网部署；2026-08-11 验证登录页、健康接口和法律页面可访问。当前仍无域名、ICP/公安备案和高可用验证；新的部署与验收事实以 [DEPLOYMENT_V3.md](DEPLOYMENT_V3.md) 为准。
