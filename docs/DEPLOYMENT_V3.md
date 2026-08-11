# InsightFlow Agent 大陆生产部署手册（V3，阶段 6D-3）

> 本文档是**部署手册**：在干净 Ubuntu/Debian x86_64 服务器上从零部署、日常升级、回滚、
> 备份恢复与合规展示的完整操作说明。手册中的每条命令都与仓库脚本逐项一致，
> 并已在独立临时环境演练验证。
>
> 当前项目已部署到 <https://43.153.181.237/>。2026-08-11 已验证 TLS、登录页、`/api/health`、
> `/api/public/site` 和三类法律页面可访问。真实备案号、真实运营主体信息、真实 API Key
> 一律不进入本仓库；当前没有域名/ICP备案/公安备案，`public_launch_enabled` 仍为 false。

## 1. 部署形态

| 方案 | 前端 | 后端 | 适合 |
| --- | --- | --- | --- |
| A. 单机 Docker（本手册主线） | Nginx 容器（生产镜像） | backend + worker + mcp 容器，`docker-compose.prod.yml` | 腾讯云等大陆 VPS |
| B. Vercel + Render/Railway/Fly.io | Vercel 静态托管 | Render/Railway/Fly.io 单容器 | 低成本海外演示 |
| C. 纯本地/内网 | `npm run build` + 任意静态服务 | uvicorn + worker | 简历演示、离线演示 |

本手册只覆盖方案 A（大陆公众站）。

## 2. 服务器推荐配置（腾讯云大陆）

- **机型**：轻量应用服务器或 CVM，**2 核 4G 起**（worker 容器 mem_limit 2200m、backend 900m、mcp 512m、web 192m）。
- **系统**：Ubuntu 22.04/24.04 或 Debian 12（x86_64）。
- **带宽**：1～3 Mbps 起（演示够用）；上传大文件场景提高带宽。
- **安全组开放端口（仅这些）**：

| 端口 | 协议 | 用途 | 是否对公网 |
| --- | --- | --- | --- |
| 80 | TCP | HTTP（自动跳转 HTTPS） | 是（云安全组） |
| 443 | TCP | HTTPS | 是（云安全组） |
| 22 | TCP | SSH 管理 | 仅管理员 IP |
| 8000 / 8765 / 5173 | - | backend / MCP / 前端开发端口 | **禁止开放**（容器仅 expose，不发布到宿主机） |

- **验证端口不监听**：部署后执行 `ss -ltn` 确认宿主机只监听 80/443/22。

## 3. 目录与持久化结构

| 目录 | 内容 | 说明 |
| --- | --- | --- |
| `/opt/insightflow/releases/<version>` | 每个版本的**只读源码包**（`git archive` 生成） | 升级 = 新版本目录，绝不覆盖旧版本 |
| `/opt/insightflow/current` | 指向当前版本的 symlink | systemd 与运维脚本的固定入口 |
| `/srv/insightflow/data` | SQLite 主库（`insightflow.db`） | 必须持久盘 |
| `/srv/insightflow/storage` | uploads / charts / reports / retrieval | 必须持久盘 |
| `/srv/insightflow/backups` | 备份（`backup.sh` 生成） | 持久盘 + 定期异地 |
| `/srv/insightflow/secrets/tls` | `fullchain.pem` / `privkey.pem` | 0700，证书 |
| `/srv/insightflow/secrets/acme` | certbot ACME 文件 | 0700 |
| `/srv/insightflow/logs` | app / nginx / deploy / backup / cleanup | 日志轮转 |

`INSIGHTFLOW_ROOT`（`deploy/.env.production` 中配置）指向 `/srv/insightflow`；
`docker-compose.prod.yml` 的所有 volume 都以 `${INSIGHTFLOW_ROOT}` 为根。

## 4. 发布包制作（Git Tag → 源码包 → SHA-256 → 上传）

在**构建机**（任意 Linux/macOS/Windows + Git）上执行：

```bash
# 1. 打 Tag（版本号示例 v3.0.0；含 Release Notes）
git tag -a v3.0.0 -m "InsightFlow Agent v3.0.0 生产发布"
git push origin v3.0.0

# 2. 生成生产源码包（只含已提交内容，不含 .git）
#    注意：必须用 -c core.autocrlf=false 保证 shell 脚本以 LF 输出。
#    Windows 上 core.autocrlf=true 会让 git archive 输出 CRLF，
#    导致 Linux 上 bash 执行 `set -o pipefail\r` 失败。
git -c core.autocrlf=false archive --format=tar.gz -o insightflow-v3.0.0.tar.gz \
  --prefix=insightflow-v3.0.0/ v3.0.0
# 在 Linux 构建机上执行则无需该参数（默认无 autocrlf）。

# 3. 计算 SHA-256 校验和
sha256sum insightflow-v3.0.0.tar.gz > insightflow-v3.0.0.tar.gz.sha256
```

服务器上校验（下载后）：

```bash
sha256sum -c insightflow-v3.0.0.tar.gz.sha256
```

解压并放置到只读 release 目录（版本号示例 v3.0.0）：

```bash
sudo install -d -m 0755 /opt/insightflow/releases
sudo tar -xzf insightflow-v3.0.0.tar.gz -C /opt/insightflow/releases/
sudo mv /opt/insightflow/releases/insightflow-v3.0.0 /opt/insightflow/releases/v3.0.0
# 校验解压内容包含部署脚本
ls /opt/insightflow/releases/v3.0.0/deploy/scripts/

# 重要：git archive 的源码包不保留可执行位，脚本需显式恢复执行权限
# （upgrade.sh/rollback.sh 内部直接调用 backup.sh 等脚本，缺少 x 位会 Permission denied）
sudo chmod +x /opt/insightflow/releases/v3.0.0/deploy/scripts/*.sh
```

设置 current symlink（首次部署或升级切换）：

```bash
sudo ln -sfn /opt/insightflow/releases/v3.0.0 /opt/insightflow/current
```

> 镜像构建有两种方式：release 目录内 `compose build backend web`（需服务器有构建环境），
> 或构建机 `docker save` 导出 tar 后服务器 `deploy/scripts/load-images.sh` + `SKIP_BUILD=1`。

## 5. 首次部署（从零）

前置条件：

1. 域名已解析到服务器（DNS A 记录，见第 6 节）；
2. 已购买/生成 TLS 证书并放入 `/srv/insightflow/secrets/tls/`；
3. 在 `/opt/insightflow/current` 执行（所有脚本假设当前目录为 current release）。

```bash
cd /opt/insightflow/current

# 1. 生成生产环境配置（只生成密钥与管理员密码文件，不输出密钥）
python3 deploy/scripts/generate_secrets.py \
  --template deploy/.env.production.example \
  --output /opt/insightflow/current/deploy/.env.production \
  --admin-password-file /srv/insightflow/secrets/admin-password.txt

# 2. 编辑 deploy/.env.production，替换全部 replace_ 占位符（见第 7 节环境变量清单）
sudoedit deploy/.env.production
# 必须填写：PUBLIC_SITE_URL、CORS_ORIGINS、DEEPSEEK_API_KEY、
#           SITE_OPERATOR_NAME、SITE_CONTACT_EMAIL、ICP_FILING_NUMBER、
#           PRIVACY_POLICY_VERSION、TERMS_VERSION、AI_MODEL_DISPLAY_NAME
# PUBLIC_LAUNCH_ENABLED=true 时未填完会启动失败（门禁）

# 3. 证书就位（必须存在 fullchain.pem + privkey.pem）
sudo install -d -m 0700 /srv/insightflow/secrets/tls
# 将证书放入后：
sudo chmod 0644 /srv/insightflow/secrets/tls/fullchain.pem
sudo chmod 0600 /srv/insightflow/secrets/tls/privkey.pem

# 4. 执行首次部署（root；创建目录 → 构建镜像 → Alembic 0014 head → 创建管理员
#    → 启动 backend/mcp/worker → readiness+MCP 健康 → 启动 web）
sudo bash deploy/scripts/deploy.sh
```

`deploy.sh` 依次完成：校验环境与证书 → 创建持久化目录 → `compose build backend web`
→ 空库 `alembic upgrade head`（0014）→ `python -m app.cli.create_admin`（交互创建管理员）
→ `compose up -d backend mcp worker` → `wait_readiness 45` + `wait_mcp_healthy 45`
→ `compose up -d web` → `nginx -t` → 写 `deployed-version`。

部署完成后：

```bash
# 四服务健康检查
sudo bash deploy/scripts/healthcheck.sh && echo OK
# 管理员登录后创建第一个邀请码（后台「邀请码」页）
```

BGE 模型缓存（生产需要真实 embedding 时）：在构建机下载模型后
`scp` 上传到 `/srv/insightflow/data/model_cache/`（挂载为 `/app/data/model_cache`），
或首次启动后由 `LocalEmbeddingProvider` 在线下载（需公网）。

## 6. DNS、TLS 与 HTTPS

- **DNS A 记录**：`www.example.cn` 与 `example.cn` 均解析到服务器公网 IP（备案域名）。
- **TLS 证书位置**：`/srv/insightflow/secrets/tls/fullchain.pem` + `privkey.pem`。
- **首次证书**：可先用自签名或云厂商证书验证链路，正式上线前换为 Let's Encrypt 或云证书。
- **证书续期（Let's Encrypt）**：

```bash
sudo certbot certonly --webroot -w /var/www/certbot \
  -d example.cn -d www.example.cn \
  --deploy-hook "bash /opt/insightflow/current/deploy/scripts/certbot-deploy-hook.sh"
```

`deploy/scripts/certbot-deploy-hook.sh` 会把续期证书安装到 `/srv/insightflow/secrets/tls/`
（校验后）并调用 `deploy/scripts/reload-nginx.sh` 平滑 reload。
Nginx 容器通过 volume 挂载证书；手动替换证书后同样执行 `deploy/scripts/reload-nginx.sh`。

## 7. 环境变量清单

完整模板：`deploy/.env.production.example`（全部占位符）。关键项：

| 变量 | 说明 | 必须 |
| --- | --- | --- |
| `AUTH_SECRET_KEY` | 高熵随机密钥（会话/CSRF 签名；`generate_secrets.py` 生成） | 是 |
| `DATABASE_URL` / `ALEMBIC_DATABASE_URL` | 指向持久盘 SQLite（`sqlite:////app/data/insightflow.db`） | 是 |
| `UPLOAD_DIR` / `REPORT_DIR` / `CHART_DIR` / `BACKUP_DIR` | 容器内持久化目录 | 是 |
| `CORS_ORIGINS` / `PUBLIC_SITE_URL` | 前端真实来源（https 正式域名） | 是 |
| `DEEPSEEK_API_KEY` + `DEEPSEEK_MODEL` | DeepSeek 生产配置 | 按需 |
| `ENGINEERING_MCP_ENABLED=true` + `ENGINEERING_MCP_URL=http://mcp:8765/mcp` + `ENGINEERING_MCP_INTERNAL_TOKEN` + `ENGINEERING_MCP_ALLOW_CONTAINER_BIND=true` | MCP 独立容器 | 是 |
| `PUBLIC_LAUNCH_ENABLED` | 大陆公众站开关（true 时门禁校验） | 上线后是 |
| `SITE_OPERATOR_NAME` / `SITE_CONTACT_EMAIL` | 运营主体与联系/投诉邮箱 | 公众站是 |
| `ICP_FILING_NUMBER` / `ICP_FILING_URL` | 工信部备案号与链接（`https://beian.miit.gov.cn/`） | 公众站是 |
| `PUBLIC_SECURITY_FILING_NUMBER` / `PUBLIC_SECURITY_FILING_URL` | 公安备案号（可空=办理中）与平台链接 | 公众站按需 |
| `AI_MODEL_DISPLAY_NAME` / `AI_MODEL_FILING_NUMBER` / `AI_ASSISTED_NOTICE` | AI 标识配置 | 公众站是 |
| `PRIVACY_POLICY_VERSION` / `TERMS_VERSION` | 法律页面版本号 | 公众站是 |
| `AUTH_COOKIE_SECURE` / `TRUST_PROXY_HEADERS` / `TRUSTED_PROXY_IPS` / `ENABLE_HSTS` | HTTPS 安全项（模板已含正确值） | 是 |

**密钥边界**：`.env` 不进 Git；容器只从环境变量读密钥；`generate_secrets.py`
输出文件权限 0600，stdout 不打印任何密钥。

## 8. 日常运维

### 8.1 服务与日志

```bash
cd /opt/insightflow/current
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml ps
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml logs --tail=200
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml logs -f backend
```

### 8.2 健康检查与监控

```bash
sudo bash deploy/scripts/healthcheck.sh   # 退出 0 = 全部正常；非零 = 异常项数
```

healthcheck.sh 检查：四服务容器运行、API liveness/readiness（含 MCP 视图）、
Alembic head、storage 可写、Worker 心跳、**MCP 工具发现**、Nginx 配置、
磁盘使用率、48 小时内备份存在、TLS 证书剩余有效期。

仓库提供 systemd 定时任务（`deploy/systemd/`）：

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now insightflow-health.timer insightflow-backup.timer
```

- `insightflow-health.timer`：每 15 分钟跑 `healthcheck.sh`，非零即 journal 告警；
- `insightflow-backup.timer`：每日备份；
- `insightflow-cleanup-dry-run.timer`：每周清理预演。

告警建议：云监控（CPU/内存/磁盘）+ 定时任务失败告警（systemd journal）；
公网探测 `https://<域名>/api/health` 每 5 分钟一次。

### 8.3 备份与异地备份

```bash
sudo bash deploy/scripts/backup.sh
```

每次备份 = SQLite Online Backup 一致性 `database.sqlite3` + 完整 `storage.zip`
+ 记录大小/SHA-256 的 `manifest.json`；**不含** `.env`、证书和密钥。
脚本不自动删除旧备份；保留期由 `BACKUP_RETENTION_DAYS` 与人工管理。

校验与恢复演练：

```bash
# 校验 manifest 与文件 SHA
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml \
  exec -T backend python -m app.maintenance.backup --verify /app/backups/<备份目录名>

# 恢复到独立副本（不覆盖生产库；目标已存在会拒绝）
sudo docker compose --env-file deploy/.env.production -f docker-compose.prod.yml \
  exec -T backend python -m app.maintenance.restore \
  --backup-dir /app/backups/<备份目录名> \
  --destination /app/backups/<备份目录名>/restore-drill.sqlite3
```

异地备份：至少每周把加密后的最新备份目录下载到另一台设备；
每月做一次完整恢复演练（见第 10 节演练记录）。

### 8.4 清理

```bash
sudo bash deploy/scripts/cleanup.sh               # dry-run 预演
sudo CONFIRM_CLEANUP=APPLY_CLEANUP bash deploy/scripts/cleanup.sh --apply
```

## 9. 日常升级与回滚

### 9.1 升级（v3.0.0 → v3.0.1）

```bash
# 1. 新版本源码包放置为 /opt/insightflow/releases/v3.0.1（见第 4 节）
# 2. 切到新版本目录执行（不会触碰旧 release 目录）
cd /opt/insightflow/releases/v3.0.1
# 3. 复制生产配置（只保留一份 .env.production，0600）
sudo cp /opt/insightflow/current/deploy/.env.production deploy/.env.production
# 4. 升级（自动：校验 → 备份 → 构建 → 停写 → 迁移 → 启动 → readiness+MCP → web）
sudo bash deploy/scripts/upgrade.sh v3.0.1
# 5. 全部通过后切换 symlink
sudo ln -sfn /opt/insightflow/releases/v3.0.1 /opt/insightflow/current
```

`upgrade.sh` 顺序：`compose config` → `backup.sh`（升级前自动备份，仍运行旧版）
→ `compose build backend web`（或 `SKIP_BUILD=1` 用已加载镜像）
→ `compose stop worker backend mcp` → `alembic upgrade head`
→ `compose up -d backend mcp worker` → `wait_readiness 45` + `wait_mcp_healthy 45`
→ `compose up -d web` → `nginx -t` → 写 `deployed-version`。
迁移或 readiness 失败立即退出 1 并记录，**不切换 Nginx、不反复迁移**。

### 9.2 回滚

仅代码回滚（旧代码明确兼容当前 schema 时）：

```bash
cd /opt/insightflow/current
sudo bash deploy/scripts/rollback.sh --code-only \
  <旧backend镜像:不可变标签> <旧web镜像:不可变标签>
```

完整恢复（迁移不可安全回滚时，用升级前备份恢复数据库与 storage）：

```bash
sudo CONFIRM_RESTORE=RESTORE_DATABASE_AND_STORAGE \
  bash deploy/scripts/rollback.sh --restore-backup \
  <旧backend镜像:不可变标签> <旧web镜像:不可变标签> <备份目录名>
```

`rollback.sh` 先 `--verify` 备份（manifest/SHA/一致性），停止写入，
把当前数据库与整个 storage 移到 `rollback-safety-*` 现场目录（不删除），
恢复备份后启动 backend/mcp/worker、等 readiness+MCP、再起 web。
**不要**自行执行 `alembic downgrade`，除非该 revision 已完成专门演练与数据损失评审。

## 10. 备份恢复演练（季度，隔离环境）

1. 准备隔离目录：`/srv/insightflow-drill-<日期>`（全新目录，`INSIGHTFLOW_ROOT` 指向它）；
2. 恢复 `database.sqlite3`（`restore.py --destination`）并解压 `storage.zip`；
3. 用第 5 节流程部署一套临时站点（自签名证书），启动后登录验证：
   用户、Workspace、ReviewRun、Evidence、Report 与文件资产；
4. 核对历史报告资产 SHA 与备份前一致；
5. 演练后按单文件删除规则清理隔离目录，**生产目录不被覆盖**；
6. 记录恢复耗时与数据规模（备份大小、文件数、恢复耗时）。

## 11. 大陆合规：备案展示与 AI 标识

- **ICP 备案**：工信部备案管理系统办理后，把真实备案号填入 `ICP_FILING_NUMBER`。
  全站页脚在站点底部显示备案号并链接 `https://beian.miit.gov.cn/`
  （《非经营性互联网信息服务备案管理办法》第十三条）；
  广东主体备案号不带序号，其他省网站备案号带 `-n`（门禁按两种格式校验）。
- **公安联网备案**：ICP 备案后 30 日内在全国互联网安全管理服务平台
  （`http://www.beian.gov.cn/portal/index.do`）办理；办理期间页脚显示
  "公安联网备案办理中（法定办理期限内）"，取得后填 `PUBLIC_SECURITY_FILING_NUMBER`
  并链接平台。
- **AI 标识**：智能核验页、报告页、全站页脚显示 `AI_ASSISTED_NOTICE`
  （默认"AI 辅助生成，须人工复核"）；Markdown/PDF 报告含可见 AI 辅助生成声明
  （依据《人工智能生成合成内容标识办法》，国信办通字〔2025〕2 号）。
- **合规待办（上线前）**：
  1. 真实运营主体、联系邮箱、隐私政策/用户协议版本与内容占位补充；
  2. ICP 备案号、公安备案号、生成式 AI 服务备案号（`AI_MODEL_FILING_NUMBER`）真实办理；
  3. 文件元数据隐式标识（GB 45438-2025 精确字段）——需专业合规确认后实现，未自行创造格式；
  4. 隐私政策中"数据保存期限说明""删除流程说明"占位由运营者填写；
  5. 本手册与站点展示不构成完整法律合规意见。

## 12. 验收清单（手机 + 电脑）

- 电脑：HTTPS 打开首页 → 登录 → 创建邀请码 → 注册第二账号 →
  上传文件 → 工程审查 → 智能核验 → 报告生成/下载（Markdown/PDF 含 AI 声明）→ 页脚备案展示；
- 手机（390px）：登录页、法律页、工程列表、智能核验、报告页无横向溢出；
- 跨用户隔离：第二账号访问第一账号工作区必须被拒绝；
- 端口：`ss -ltn` 仅 80/443/22；
- 日志：`docker compose logs` 无密钥、无绝对路径。

## 13. 当前公网验证与未完成项

已于 2026-08-11 验证：

- `https://43.153.181.237/` 使用受信任的 IP 地址证书与 TLS 1.3 返回 200；
- 登录页和三类法律页面可访问，桌面与 390px 无整页横向溢出；
- `/api/health` 返回 `status=ok`，`/api/public/site` 可访问。

仍未完成或未验证：

- 尚无域名、ICP 备案和公安备案；当前 `public_launch_enabled=false`，页脚没有显示“公安联网备案办理中”占位，Stage 6D-2 公网验收为 `7 passed, 1 failed`；
- IP 地址证书的自动续期、到期告警和续期失败演练尚未形成可核验证据；
- 登录后的上传、真实工程审查、MCP、Supervisor、报告下载和跨用户隔离尚未针对当前公网实例完成版本化全链验收；
- 云监控/告警、备份恢复、多用户高频并发和 SQLite 承载仍未验证（当前按单机低频演示设计）。

## 14. 故障速查

| 症状 | 处理 |
| --- | --- |
| `deploy.sh` 拒绝执行 | 证书缺失 / 数据库已存在（改用 upgrade） |
| backend unhealthy | `logs backend`；门禁报错看 `RuntimeError` 信息 |
| readiness degraded | `curl /api/health/ready` 看 checks；MCP/DeepSeek/OCR 明细 |
| 升级迁移失败 | 保持停写，`rollback.sh --restore-backup`（见 9.2） |
| 证书即将到期 | certbot 续期 + deploy-hook（见第 6 节） |
| 磁盘紧张 | `cleanup.sh --apply`（先 dry-run + 备份） |
