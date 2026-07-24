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

## V2-07 生产入口

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

## 明确边界

仓库没有购买服务器/域名，没有备案、修改 DNS、登录云控制台、连接真实服务器、申请真实证书、升级真实数据库或完成中国内地网络测试。历史 Vercel/Render 资料不再是 V2 生产默认配置。
