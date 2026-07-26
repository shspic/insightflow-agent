# V2-08 安全检查清单

本文档记录 2.0.0-rc.1 发布候选版本的安全检查结果。已完成项有证据支撑，未完成项明确标注。

## Git 安全检查

| 检查项 | 状态 | 证据 |
|--------|------|------|
| 无 `.env` 文件提交 | 通过 | `.gitignore` 包含 `.env`、`backend/.env`、`deploy/.env.production` |
| 无真实 API Key | 通过 | `grep` 未在跟踪文件中发现 base64 长度随机字符串或 Key 模式 |
| 无数据库文件 (`*.db`) | 通过 | `.gitignore` 包含 `*.db`、`backend/data/`、`data/` |
| 无证书文件 (`*.pem`、`*.key`) | 通过 | `.gitignore` 包含 `*.pem`、`*.key`、`deploy/certs/` |
| 无上传/图表/报告文件 | 通过 | `.gitignore` 包含 `backend/storage/uploads/`、`storage/`、`backups/` |
| 无 node_modules | 通过 | `.gitignore` 包含 `node_modules/`、`frontend/node_modules/` |
| 无 `__pycache__` 和 `.pyc` | 通过 | `.gitignore` 包含 `__pycache__/`、`*.pyc` |
| Git `diff --check` 无空白错误 | 通过 | 返回 0 |

## 代码安全检查

### 前端

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 无 `dangerouslySetInnerHTML` | 通过 | `grep` 未在 `frontend/src/` 中发现 |
| 无 hardcoded URL | 通过 | API 请求全部使用相对路径 `/api/v2/`，`vite.config.js` 仅配置 dev proxy 到 `127.0.0.1:8000` |
| 无真实 API Key | 通过 | 所有 token/secret 通过 Cookie 和 CSRF Header 传递，不写入 localStorage/sessionStorage |
| 安全 Markdown 渲染 | 通过 | `SafeMarkdown.jsx` 组件限制 HTML 标签，不渲染 `<script>`、`<iframe>` 等不安全标签 |
| 一次性秘密清除 | 通过 | `oneTimeSecretReducer` 确保邀请码/临时密码关闭后清除明文 |
| 权限导航控制 | 通过 | `allowedNavigation` 按用户角色控制菜单可见性 |
| 生产构建无 source map | 通过 | `vite.config.js` 设置 `build.sourcemap: false` |

### 后端

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 无 `exec()`/`eval()` 执行用户输入 | 通过 | 所有分析通过预设 Pandas 工具函数完成 |
| 无动态 import 用户指定模块 | 通过 | V2 Tool Registry 禁止动态 import |
| 无任意 Python/Shell/SQL/URL 执行 | 通过 | V2 工具注册表不包含这类工具 |
| 文件路径不拼接用户输入 | 通过 | storage key 由系统生成（UUID），不在 API 暴露真实路径 |
| SQL 查询使用参数化 | 通过 | SQLAlchemy ORM 原生防注入 |
| 无真实密钥硬编码 | 通过 | `AUTH_SECRET_KEY`、`DEEPSEEK_API_KEY` 等全部从环境变量读取 |

## 生产配置安全检查

| 配置项 | 生产要求 | 默认值来源 |
|--------|---------|-----------|
| `ENABLE_LEGACY_V1_API` | `false` | `deploy/.env.production.example` |
| `AUTH_COOKIE_SECURE` | `true` | `deploy/.env.production.example` |
| `AUTH_COOKIE_SAMESITE` | `lax` | `deploy/.env.production.example` |
| `AUTH_SECRET_KEY` | 拒绝启动 | `settings.py` 门禁：缺失或长度不足 32 字符时 raise |
| `DEBUG` | `false` | `deploy/.env.production.example` |
| `CORS_ORIGINS` | 精确域名 | 生产示例为 `https://insightflow.example.cn`，不包含 `*` |
| `TRUST_PROXY_HEADERS` | `true` | 在同域 Nginx 反向代理环境中启用 |
| `ENABLE_HSTS` | `true` | `deploy/.env.production.example` |
| HSTS Header | `max-age=31536000; includeSubDomains` | `deploy/nginx/snippets/security-headers.conf` |
| Content Security Policy | 禁止 `unsafe-eval`，限制外部来源 | `security-headers.conf` |
| X-Content-Type-Options | `nosniff` | `security-headers.conf` |
| X-Frame-Options | `DENY` | `security-headers.conf` |

## report_path / file_path 暴露风险

### V1 API（默认关闭）

`/api/files`、`/api/tasks` 的旧响应中 `report_path` 字段曾直接暴露本机绝对路径或相对路径。这些接口由 `ENABLE_LEGACY_V1_API` 控制：

- **生产 Compose**：`ENABLE_LEGACY_V1_API=false`，V1 路由完全不挂载
- **测试/本地兼容**：手动设为 `true` 时可用，但必须在无需暴露真实路径的环境中

### V2 API（已脱敏）

所有 V2 API 不使用 `report_path` 字段。报告下载通过 `storage_key`（系统生成的 UUID）鉴权下载，校验所有者和文件归属，不暴露真实存储路径。

## 权限检查

### 资源归属校验

所有 V2 资源查询均需验证 `owner_user_id` 匹配：

| 资源类型 | 检查位置 | 校验方式 |
|---------|---------|---------|
| 工作区 | `workspace_service.py` | `workspace.owner_user_id == current_user.id` |
| 工作区文件 | `workspace_files.py` | 通过 workspace 间接校验 owner |
| 任务 | `workspace_tasks.py` | 通过 workspace 间接校验 owner |
| 事件 | `workspace_tasks.py` | 通过 task → workspace 链校验 |
| 报告 | `reports_governance.py` | `report.owner_user_id == current_user.id` |
| 文件理解 | `file_understanding.py` | 通过 workspace 间接校验 |
| 文件关系 | `file_understanding.py` | 通过 workspace 间接校验 |
| 管理员接口 | `admin.py` | `require_admin` 依赖：检查 `user.role == "admin"` |

### 越权防护

- 管理员可以查看运行元数据（任务计数、Worker 状态、配额），但**不返回**普通用户报告正文、原始文件内容或未脱敏模型输入
- 跨用户工作区操作被 workspace owner 检查阻断
- 报告下载需要鉴权 Cookie 并逐级校验归属

## 密码安全

| 机制 | 实现 |
|------|------|
| 哈希算法 | Argon2id（通过 `argon2-cffi`） |
| 最小长度 | 14 字符（生产环境 `PASSWORD_MIN_LENGTH=14`） |
| 临时密码 | 管理员创建用户时随机生成，仅通过 `oneTimeSecretReducer` 展示一次，关闭后清除明文 |
| 强制改密 | 临时密码首次登录必须改密，`require_password_changed` 依赖检查 `password_changed` 标志 |
| 密码重置 | 匿名申请，生成限时 token，不直接重置为预设密码 |

## Session 安全

| 机制 | 实现 |
|------|------|
| Cookie 属性 | HttpOnly、Secure（生产）、SameSite=Lax |
| Session Token | SHA-256 哈希存储，比对时计算输入 token 的哈希 |
| CSRF | 双 Token 机制：Cookie 中的 `insightflow_csrf` + 客户端请求 Header `X-CSRF-Token` |
| 可撤销 | Session 有 `revoked_at` 字段，管理员可撤销指定会话 |
| 过期 | `expires_at` 字段，每次使用时检查 |
| Cookie 名称 | 可通过 `AUTH_COOKIE_NAME` 和 `CSRF_COOKIE_NAME` 自定义 |

## 文件上传安全

| 机制 | 实现 |
|------|------|
| 扩展名白名单 | `.csv`、`.xlsx`、`.pdf`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.md`、`.markdown` |
| MIME 校验 | 检查文件 Content-Type 与扩展名匹配 |
| 文件头校验 | 检查文件 magic bytes 匹配扩展名（防扩展名伪造） |
| 大小限制 | `UPLOAD_MAX_FILE_SIZE_BYTES`（生产默认 20MB） |
| 批量限制 | `UPLOAD_MAX_BATCH_FILES`（生产默认 10） |
| 工作区容量 | `WORKSPACE_MAX_FILES`（生产默认 50） |
| 用户存储配额 | `USER_STORAGE_QUOTA_BYTES`（生产默认 200MB） |
| 路径遍历防护 | storage key 由 UUID 生成，不接受用户提供路径；目录遍历测试用例通过 |
| 内容校验 | CSV/XLSX 检查可读性、PDF 检查页数、图片检查像素、XLSX 检查 zip 结构 |

## 容器安全

| 机制 | 实现 |
|------|------|
| 非 root 运行 | 后端容器以 UID 10001 运行（`Dockerfile` 中 `USER 10001`） |
| 只读根文件系统 | `docker-compose.prod.yml` 中 `read_only: true` |
| 资源限制 | `docker-compose.prod.yml` 配置 CPU 和内存 limits |
| 内部网络 | Backend 不映射外部端口，只通过 Nginx 反代访问 |
| 健康检查 | `/api/health/ready` 检查数据库和核心依赖 |

## 评估中的安全覆盖

deterministic 评估集包含以下安全相关类别：

| 类别 | 数量 | 断言 |
|------|------|------|
| `refusal` | 10 条 | 预期拒绝：执行 Python 脚本、Shell 命令、任意 SQL、URL 抓取 |
| `clarification` | 10 条 | 预期追问：模糊意图、缺少上下文、未说明连接字段 |
| 跨资源隔离 | 测试覆盖 | `test_user_cannot_understand_another_resource`、`test_users_and_admin_cannot_cross_access` 等 |

所有 10 条 `refusal` 案例在 deterministic 评估中验证通过（预期拒绝 = 拒绝），10 条 `clarification` 案例触发追问。关键权限越权用例（跨用户访问）100% 阻断。

## 未验证的安全项

| 项目 | 说明 |
|------|------|
| 真实 HTTPS 部署 | 证书申请、配置和证书链验证未执行 |
| WAF/DDoS 防护 | 未配置任何 Web 应用防火墙或 DDoS 防护方案 |
| 渗透测试 | 未执行专业渗透测试或自动化安全扫描 |
| 容器 CVE 扫描 | 未对基础镜像执行 CVE 扫描 |
| 数据库加密 | SQLite 文件未加密存储 |
| 异地备份加密 | 备份文件未加密 |
| 日志脱敏 | 未验证生产日志中是否误输出 token/密码/文件内容 |
| 速率限制的跨实例一致性 | SQLite 持久化限流在单机下有效，多实例需迁移到共享存储 |
| DeepSeek API 数据发送范围和隐私合规 | 需确认 DeepSeek 的数据处理协议和日志留存策略 |

## 安全检查结论

当前代码库在静态分析层面通过了基础安全检查：无密钥泄露、无 hardcoded URL、无危险函数暴露、权限检查逐级覆盖、文件上传多重校验、容器以非 root 运行。但 **生产安全远不止代码层面**。以下项必须在首次真实上线前完成：

1. 真实 HTTPS 部署并验证证书链
2. 防火墙规则：只开放 22（受限 IP）、80、443
3. 确认 DeepSeek 数据处理协议和成本上限
4. 建立异地加密备份
5. 制定安全事件响应联系人列表
