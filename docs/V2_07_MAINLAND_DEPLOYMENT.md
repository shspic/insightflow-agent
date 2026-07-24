# V2-07 中国内地单机生产部署

## 1. 交付边界

本阶段只交付代码仓库内的生产部署包，没有购买服务器或域名，没有提交备案、修改 DNS、连接云服务器、申请真实证书或执行公网访问测试。

目标是中国内地单机、5 人以内、允许排队的低并发部署：

```text
浏览器 → HTTPS Nginx
             ├─ / 与 /assets：React 静态文件
             └─ /api：单进程 FastAPI
                         ├─ SQLite WAL
                         ├─ 本地持久化 storage
                         └─ 单独的单 Worker → DeepSeek API
```

生产配置不使用 Vercel、Render、国外 CDN、远程字体、Redis、Celery、RabbitMQ、PostgreSQL或对象存储。

## 2. 服务器选择维度

- 中国内地地域，实例和主办主体满足接入商备案资格；
- Ubuntu 24.04 LTS 优先，兼容 Ubuntu 22.04 LTS；
- 优先 2 核 4GB，SSD 系统盘建议至少 60GB；
- 核对公网带宽、流量计费、快照能力、续费价格和备案资格；
- 不写死活动价格，购买前以云厂商实时页面和合同为准；
- OCR、PDF 和 Pandas 有瞬时 CPU/内存峰值，不建议 2GB 内存。

## 3. 生产 Compose

`docker-compose.prod.yml` 包含：

| 服务 | 运行方式 | 公网端口 | 资源上限 |
| --- | --- | --- | --- |
| `web` | 多阶段构建前端，Nginx 提供静态文件和反代 | 80、443 | 192MB |
| `backend` | `python -m app.cli.run_api`，固定单 Uvicorn 进程 | 无 | 900MB |
| `worker` | `python -m app.workers.task_worker`，单实例 | 无 | 2200MB |

三者使用 `unless-stopped`、Docker `json-file` 轮转、健康检查和停止宽限。`backend` 与 `worker` 使用相同镜像和相同数据库/storage bind mount。内部网络固定为 `172.30.0.0/24`，只有 `172.30.0.10` 的 Nginx 被 FastAPI 信任为代理。

`backend` 和 `worker` 以 UID/GID `10001` 非 root 运行，根文件系统只读，只允许持久卷和 `/tmp` 写入。API 不使用 `--reload`，不暴露宿主端口。

## 4. 持久化目录

```text
/srv/insightflow/
├── data/
│   ├── insightflow.db
│   └── deployed-version
├── storage/
│   ├── uploads/
│   ├── charts/
│   └── reports/
├── backups/
├── logs/
│   ├── app/
│   ├── nginx/
│   ├── deploy/
│   ├── backup/
│   └── cleanup/
└── secrets/
    ├── tls/
    │   ├── fullchain.pem
    │   └── privkey.pem
    └── acme/
```

数据库、上传、Profile/Chunk 所依赖的数据库记录、图表、三种报告、备份、证书和日志都不进入镜像。`backend/.dockerignore` 和根 `.dockerignore` 排除数据库、storage、备份、环境文件和测试临时目录。

## 5. Linux 运行依赖

后端镜像基于 `python:3.12-slim-bookworm`，通过 Debian 系统包安装：

- `tesseract-ocr`、`tesseract-ocr-chi-sim`、`tesseract-ocr-eng`；
- `poppler-utils`；
- `fonts-noto-cjk`；
- Pillow/PyMuPDF 常用的 freetype、glib、GL、JPEG、PNG、zlib、OpenMP 基础库。

DOCX 使用 `python-docx`；PDF 使用 `reportlab`；不依赖 Microsoft Word，不安装桌面环境，不提交字体文件。apt 索引在同一镜像层清理。

## 6. 环境配置

先生成不输出密钥值的本地文件：

```bash
sudo python3 deploy/scripts/generate_secrets.py \
  --template deploy/.env.production.example \
  --output deploy/.env.production \
  --admin-password-file /srv/insightflow/secrets/initial-admin-password.txt
```

然后人工替换所有 `replace_`/`your_` 占位符。核心配置：

- 安全：`ENV=production`、`DEBUG=false`、强随机 `AUTH_SECRET_KEY`、`AUTH_COOKIE_SECURE=true`、`ENABLE_LEGACY_V1_API=false`；
- 同域：`PUBLIC_SITE_URL`、精确 `CORS_ORIGINS`，`AUTH_COOKIE_DOMAIN` 通常留空以使用 host-only Cookie；
- 代理：`TRUST_PROXY_HEADERS=true`、`TRUSTED_PROXY_IPS=172.30.0.10`；
- 数据：绝对容器路径、WAL、30 秒 busy timeout；
- 模型：`DEEPSEEK_API_BASE`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`；
- OCR、Worker、任务预算、上传/存储/报告配额、保留期和日志级别。

生产示例使用 `DEEPSEEK_MODEL=deepseek-v4-flash`，但模型完全可配置。旧 `deepseek-chat` 和 `deepseek-reasoner` 被 readiness 视为不可用配置。Key、模型或 HTTPS Base 无效时，API 仍以确定性降级模式启动，`/api/health/ready` 返回 `degraded`，真实模型调用不会被冒充为成功。

## 7. 两种交付路径

### 7.1 服务器直接构建

本地生成不含 `.git`、`.env`、数据库和用户数据的发布压缩包，上传到服务器 `/opt/insightflow/releases/<版本>`，解压后把 `/opt/insightflow/current` 指向该版本。服务器不必访问 GitHub；但构建仍需要可用的基础镜像、Debian、PyPI 和 npm 包来源。不要硬编码未经确认的镜像加速地址。

```bash
sudo bash deploy/scripts/deploy.sh
```

### 7.2 本地构建后传输

在能访问依赖源的同架构 Linux 构建机执行：

```bash
docker compose --env-file deploy/.env.production \
  -f docker-compose.prod.yml build backend web
docker save -o insightflow-images-<版本>.tar \
  insightflow-backend:local insightflow-web:local
sha256sum insightflow-images-<版本>.tar > insightflow-images-<版本>.tar.sha256
```

把发布包、镜像 tar 和校验文件传到服务器，校验后：

```bash
sha256sum -c insightflow-images-<版本>.tar.sha256
sudo bash deploy/scripts/load-images.sh insightflow-images-<版本>.tar
sudo SKIP_BUILD=1 bash deploy/scripts/upgrade.sh <版本>
```

也可以推送到已确认可访问的国内容器镜像仓库，再通过生产环境变量指定不可变版本标签；仓库选择和登录由用户完成。

## 8. 首次部署

前置条件：服务器初始化完成、域名/备案/DNS/证书已按对应文档完成、生产环境文件没有占位符。

```bash
cd /opt/insightflow/current
sudo docker compose --env-file deploy/.env.production \
  -f docker-compose.prod.yml config --quiet
sudo bash deploy/scripts/deploy.sh
```

脚本只允许空数据库首次执行，顺序为：

1. 校验生产配置和证书；
2. 创建并授权持久化目录；
3. 构建 backend/web；
4. 对空数据库执行 `alembic upgrade head`；
5. 交互调用现有 `app.cli.create_admin`；
6. 启动 backend 和 worker；
7. readiness 通过后启动 Nginx；
8. 校验 `nginx -t` 并记录部署版本。

随后人工完成管理员登录、修改/保管初始凭据、创建第一个邀请码和普通用户端到端验收。脚本不会自动执行备案、DNS 或公网部署。

## 9. SQLite 生产强化

- 每个连接启用 `foreign_keys=ON`；
- 文件数据库使用 `journal_mode=WAL`、`synchronous=NORMAL`；
- SQLAlchemy/SQLite busy timeout 默认 30 秒；
- `pool_pre_ping` 和连接回收；
- API 固定 1 个进程、Worker 固定 1 个实例；
- 备份使用 SQLite Online Backup API 后执行 `PRAGMA integrity_check`；
- API 生产启动和 readiness 都核对 Alembic 当前 revision 等于单一 head。

这是工程建议下的低并发方案，不适合多机。出现以下任一趋势时应评估 PostgreSQL 和专业队列：活跃用户明显超过 5 人、同时任务常超过 1～2 个、频繁出现写锁、数据库/事件持续快速增长、需要多实例或高可用。这些是建议阈值，不是绝对规则。

## 10. 自动检查

```bash
docker compose --env-file deploy/.env.production \
  -f docker-compose.prod.yml config --quiet
sudo bash deploy/scripts/healthcheck.sh
```

健康脚本检查容器、liveness、readiness、Alembic head、storage 写入、Worker 心跳、Nginx、磁盘、内存、48 小时内备份和 14 天证书有效期，并以异常数量作为非零退出码。

更多步骤：

- [服务器初始化](V2_07_SERVER_SETUP.md)
- [域名、备案与 HTTPS](V2_07_DOMAIN_ICP_HTTPS.md)
- [运维手册](V2_07_OPERATIONS_RUNBOOK.md)
- [上线验收](V2_07_MANUAL_ACCEPTANCE.md)
