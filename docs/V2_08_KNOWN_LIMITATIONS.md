# V2-08 已知限制清单

本文档列出 2.0.0-rc.1 发布候选版本的所有已知限制。这些限制是当前架构和开发阶段的自然结果，其中多数已在 [README.md](../README.md) 当前限制一节中概括，此处逐一展开说明。

## 基础设施限制

### 单机单 Worker

当前使用 SQLite 持久化队列，由单个独立 Python 进程（`task_worker`）通过租约认领和执行任务。不支持多 Worker 并行、跨机器任务分发或共享队列协调。

**影响**：同一时间只有一个任务在执行，后续任务需排队等待。适合 5 人以内低并发演示，不适合生产级多用户并发。

### SQLite 数据库

SQLite 配置了 WAL 模式、busy timeout（30s）和外键约束，已通过低并发测试。但 SQLite 的文件级锁定在多个并发写入场景下会成为瓶颈。

**影响**：注册、上传、理解和任务创建等需写入的操作无法高并发执行。生产环境建议迁移到 PostgreSQL。

**现状**：所有 SQLAlchemy 模型和 Alembic 迁移已使用兼容写法（不使用 PostgreSQL 特有类型），迁移路径已预留。

### 5 人以内低并发

基于单 Worker + SQLite 架构，设计目标为 5 人以内同时使用。服务端配额变量（`USER_CONCURRENT_TASKS=1`、`USER_DAILY_TASKS=20`、`SYSTEM_MAX_RUNNING_TASKS=1`）均围绕此规模配置。

**影响**：不保证 >= 6 人同时使用时的队列延迟、连接池或数据库锁表现。

## 功能限制

### 文件理解接口仍是同步调用

`POST /api/v2/workspaces/{workspace_id}/files/*/understand` 在 HTTP 请求周期内完成文件解析和 Profile 生成，阻塞请求直到完成。大文件（尤其是多 Sheet XLSX 或高页数 PDF）可能导致请求超时。

**现状**：接口已设计为可将内部逻辑迁移到任务队列，但当前阶段未执行此迁移。

### 不支持任意节点暂停后原地恢复

任务执行过程中不能手动暂停任意步骤并在原位恢复。当前支持的是：

- **协作式取消**：Worker 在步骤边界检查取消标志，取消后任务进入 `cancelled` 终态
- **失败步骤局部重试**：失败步骤及下游依赖可局部重试，上游成功步骤资产复用
- **租约过期恢复**：Worker 异常退出后，租约过期，下一个轮询周期重新认领并从中断处继续

**不支持**：在 `file_understanding_agent` 执行到一半时暂停、然后数小时后从该 Agent 中间状态恢复。

### RAG 使用关键词/TF-IDF，非生产级向量数据库

当前检索方案使用轻量 TF-IDF + 关键词匹配，不依赖 Chroma、FAISS 或其他向量数据库。文件分块存入 `file_chunks` 表，检索通过对用户问题做关键词提取后在 chunk 文本中匹配。

**影响**：检索效果受限于关键词质量和同义词覆盖，不支持语义相似度排序。适合演示检索流程（分块、检索、返回页码和引用片段），但不适合大规模文档或复杂查询场景。

### OCR 依赖 Tesseract，中文识别需人工复核

OCR 功能通过 `pytesseract` 调用系统 Tesseract OCR 引擎。识别准确率取决于：

- Tesseract 版本和安装语言包
- 图片清晰度、字体大小、旋转角度、压缩质量
- 版面复杂度（表格、多栏、混合字体）

**影响**：中文 OCR 结果不能视为可直接使用的精确文本，必须由用户人工核对。OCR 未配置时系统返回明确中文提示，不会崩溃。

### 扫描 PDF OCR 受页数/DPI/超时限制

扫描 PDF 的低文本页 OCR 有以下硬限制（可由环境变量调整）：

| 参数 | 生产默认值 | 说明 |
|------|-----------|------|
| `PDF_OCR_MAX_PAGES` | 50 | 超过此页数只处理前 N 页 |
| `PDF_OCR_DPI` | 150 | 渲染分辨率 |
| `PDF_OCR_MAX_PIXELS_PER_PAGE` | 12,000,000 | 单页像素上限 |
| `PDF_OCR_TIMEOUT_SECONDS` | 120 | 单页超时 |
| `PDF_OCR_MIN_TEXT_CHARS` | 20 | 低于此字符数判定为低文本页，触发 OCR |

**影响**：超过 50 页的扫描 PDF 后部页不处理；高 DPI 扫描件在低 DPI 渲染下识别率下降。

## 模型与评估限制

### DeepSeek 模型名未核实

`DEEPSEEK_MODEL` 环境变量默认值为占位符。V2-04 中引入了 "degraded mode" —— 当模型名与已知有效列表不匹配时，系统不会假装成功，而是走确定性降级路径。但当前未真实调用 DeepSeek API 验证模型可用性、延迟和输出格式。

**影响**：首次真实配置 DeepSeek 时，需要用户确认模型名正确并能正常返回 JSON Schema 约束的输出。

### 未完成真实 DeepSeek 质量评估

全部 85 条评估案例都是 deterministic 模式运行（仅规则自检），未在 `mode=model` 下调用真实 DeepSeek 产生评估结果。因此不存在：

- 任务分类准确率（真模型 vs 预期）
- 报告质量评分（LLM-as-judge 或其他指标）
- OCR + DeepSeek 联合识别准确率
- RAG + DeepSeek 联合问答质量

### deterministic 评估的 1.0 只是规则自检

`task_success_rate=1.0` 不代表 Agent 或 DeepSeek 的真实准确率。详细解释见 [V2_08_FINAL_ACCEPTANCE.md](V2_08_FINAL_ACCEPTANCE.md) 中 "Deterministic 评估" 一节的 "重要说明"。

## 部署与运维限制

### 未执行国内服务器购买、域名、备案、HTTPS

仓库不包含任何服务器购买记录、域名所有权凭证、ICP 备案信息或真实 HTTPS 证书。V2-07 的所有部署文档和运维脚本均为预编写，未在真实服务器上验证。

### 未执行生产 Docker 构建和容器运行测试

V2-07 验证期间尝试构建生产 Docker 镜像（`docker compose -f docker-compose.prod.yml build`），在获取 Docker Hub 官方 Python/Nginx 基础镜像鉴权 token 时因 IPv6 连接超时失败，未进入 Dockerfile 指令执行阶段。因此：

- 未验证生产 backend/web 镜像能否成功构建
- 未启动隔离生产容器验证 health/readiness/HTTPS/SSE 运行态

### 未迁移 PostgreSQL、对象存储、专业队列

当前全部使用 SQLite + 本地文件存储 + 数据库轮询队列。README 和 V2-07 文档已预留迁移路径，但以下工作完全未执行：

- PostgreSQL schema 兼容性复查（所有 SQLAlchemy 模型使用兼容类型，但未经实际 PostgreSQL 验证）
- 对象存储（S3/OSS/MinIO）集成
- Redis/RabbitMQ/Celery 队列集成

### 未建设多机高可用

当前为单机部署包，不涉及负载均衡、数据库主从复制、存储冗余或多机房容灾。

## 前端限制

### 前端未进行完整 E2E 测试

前端测试仅覆盖 10 项纯逻辑单元测试（`frontend/src/utils/ui.test.js`），未使用 Playwright 或同等工具进行浏览器端 E2E 测试，包括：

- 完整注册 → 登录 → 改密流程
- 工作区创建 → 文件上传 → 批量理解流程
- 任务草稿 → 追问 → 计划确认 → 执行 → 报告流程
- 不同屏幕尺寸下的响应式表现
- SSE 断线恢复和降级轮询的实际浏览器行为

### 大型事件列表采用最近 300 条上限

任务事件列表和调度历史在 SSE 和轮询响应中限制最近 300 条，前端不做虚拟滚动或服务端分页。对于执行步骤超过 300 步的极端任务，早期事件不可见。

## 代码遗留

### 旧 V1 API 通过 ENABLE_LEGACY_V1_API 控制

V1 时期的 `/api/files`、`/api/tasks`、`/api/reports` 接口代码仍存在于仓库中。通过环境变量 `ENABLE_LEGACY_V1_API` 控制（生产默认 `false`），但代码未被删除。

**影响**：如果生产环境误将此变量设为 `true`，旧接口会绕过 V2 的多用户隔离和权限检查。V2-07 生产 Compose 已有门禁强制检查。

### Starlette 弃用状态码警告

代码中使用 `from fastapi import status` → `status.HTTP_200_OK` 等常量。FastAPI 的 `status` 模块实际上是 `starlette.status` 的重新导出。这导致 pytest 输出中出现大量 starlette 弃用警告（约 1708 条中的主要部分）。

**涉及文件**：约 12 个文件（`backend/app/api/v2/*.py`、`backend/app/api/dependencies/auth.py` 等），约 72 处引用。

**性质**：第三方依赖（FastAPI/Starlette）的内部行为，不影响任何功能。不修改。

### Alembic 迁移文件中的 datetime.utcnow() 弃用警告

6 个 Alembic 迁移文件中的 `datetime.utcnow()` 是已提交迁移的一部分。根据项目规则（已提交迁移不可修改），保留了原始写法。

**涉及文件**：`backend/alembic/versions/20260724_0006_v2_reports_governance_evaluation.py` 等

**性质**：`alembic upgrade` 和 `alembic downgrade` 运行时产生弃用警告，但不影响迁移正确性。

## 建议后续优先解决项

1. 解决 Docker 构建网络问题，完成生产容器构建和运行态验证
2. 在本地环境配置真实 DeepSeek API Key，执行完整的 mode=model 评估
3. 使用 Playwright 编写 5-8 条关键路径的浏览器 E2E 测试
4. 补充 `screenshots/` 真实截图
5. 到达真实服务器后执行 V2-07 手动验收清单
