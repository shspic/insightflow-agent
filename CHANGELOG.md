# InsightFlow Agent 变更日志

## [Unreleased] — 2026-08-11

- 已完成单机公网 HTTPS 部署：<https://43.153.181.237/>。2026-08-11 验证登录页、`/api/health`、法律页面和 TLS 可访问。
- 当前测试口径：后端 `959 collected`（本轮全量未在 300 秒内完成，不能写 959 passed）；前端 `116 passed`；生产构建 `92 modules transformed`；公网 Stage 6D-2 为 `7 passed, 1 failed`。
- 公网待办：`public_launch_enabled` 仍为 false，页脚缺少公安备案办理中占位；域名、ICP备案、公安备案、高可用与多用户并发尚未完成或验收。

## [3.0.2] — 2026-08-10

- 当前 `master` 提交 `b7343e8` 与 Git Tag `v3.0.2` 一致；`VERSION` 已由过时的 `2.0.0-rc.1` 对齐为 `3.0.2`。
- V3 工程投标审查主线包含 BM25+BGE+RRF 混合检索、Streamable HTTP MCP、Verification Agent、四节点 Supervisor、Quality Gate 2.0 与 Stage 6A～6D 验收资产。

## [2.0.0-rc.1] — 2026-07-24

### V2 正式版发布候选（Release Candidate 1）

本版本是 V2 完整产品的主线代码封板版本。自 V1 单用户演示版以来，完成了以下全部里程碑。

### V2-01：数据库迁移基线与身份模型
- 引入 Alembic 迁移系统
- 新增 users、auth_sessions、invite_codes、workspaces 等 V2 核心数据表
- 为旧 files/tasks 表增加可空 owner_user_id 字段

### V2-02：认证、管理员与工作区隔离
- Argon2id 密码哈希、Session Cookie、双 Token CSRF
- 邀请码注册、人工密码重置、强制改密
- 管理员 CLI 初始化、用户管理、审计日志
- 工作区 CRUD、归档/恢复使用
- 完整前端认证页面和路由守卫

### V2-03：统一文件理解与关系确认
- 五类文件（CSV/XLSX/PDF/图片/Markdown）统一理解和 Profile
- 版本化 Profile、系统角色标签建议与用户确认
- 文件关系候选（规则+模型）、确认/拒绝/修正
- Workspace Context（脱敏、裁剪、版本化）
- 上传安全校验和配额控制

### V2-04：可靠任务执行与多 Agent 架构
- 主动追问（最多两轮）、版本化计划生成和确认
- 数据库任务队列、独立 Worker、租约与心跳
- SSE 实时事件、断线恢复、轮询降级
- 协作式取消、失败步骤局部重试
- Supervisor + File Understanding / Data Analysis / Document Research / Report / Quality Review 五个专业 Agent
- Tool Registry 和 Prompt Registry

### V2-05：报告交付、治理与评估
- 报告版本管理、三模板（综合分析/学生调研/岗位分析）
- Markdown/DOCX/PDF 三格式导出
- 扫描 PDF 分页 OCR
- 用户反馈、重新生成
- Prompt 版本管理
- 集中配额系统、用量追踪
- 85 条 deterministic 评估集
- 清理和备份/恢复系统
- Production 安全门禁

### V2-06：全站 UI 重设计
- 集中设计 Token（浅色/深色/跟随系统）
- 公共组件体系（40+组件）
- 桌面可折叠侧栏、移动抽屉导航
- 工作区详情子路由
- 报告中心、文件关系、任务执行时间线
- 响应式覆盖 360px/768px/1024px/1440px
- 基础无障碍支持

### V2-07：中国内地单机生产部署包
- 三服务生产 Compose（Nginx/Backend/Worker）
- Nginx 同域 HTTPS、SPA fallback、SSE 无缓冲
- 非 root 运行、只读根文件系统、资源限制
- SQLite WAL、生产门禁、密钥管理
- 备份/恢复/升级/回滚/清理全套运维脚本
- systemd timer 和 logrotate
- 五份部署文档和 36 项上线验收清单

### V2-08（本版本）：最终回归验收与项目封板
- 全仓库审计：修复过时引用、清理文档不一致
- 弃用警告治理：datetime.utcnow() → timeutils.utcnow()
- Pandas 警告修复：format="mixed" + 移除冗余 warnings.catch_warnings()
- DeepSeek 模型名配置化：移除硬编码的未核实模型名
- 隔离验收环境：scripts/ 脚本和 .runtime/ 目录
- 合成演示资料：examples/demo_workspace/
- 后端 90 测试全部通过，前端 10 测试全部通过
- Alembic 从零升级→回退→再升级通过
- deterministic 评估 85 条通过（规则自检）
- 前端生产构建成功（77 模块）
- Docker Compose 配置校验通过
- pip check 无冲突、compileall 通过
- 版本号 2.0.0-rc.1

### 尚未完成
- 未购买中国内地服务器/域名/ICP 备案/HTTPS 证书
- 未执行公网部署和真实网络测试
- 未使用真实 DeepSeek 进行质量评估
- 未使用真实扫描 PDF 完成生产 OCR 验收
- 未迁移 PostgreSQL/对象存储/专业队列
- 未建设多机高可用
- 未创建 Git Tag 或 GitHub Release

---

## [1.0.0] — 2026-07-18（审计基线）

### 初始完整版本（V1 单用户演示版）

- FastAPI + React 前后端
- 文件上传（CSV/XLSX/PDF/图片）
- Pandas 数据分析、Matplotlib 图表
- PyMuPDF PDF 提取、TF-IDF 检索
- Tesseract OCR
- LangGraph 线性工作流
- Markdown 报告
- Docker Compose
- Vercel + Render 公网演示
