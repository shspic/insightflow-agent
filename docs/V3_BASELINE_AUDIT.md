# InsightFlow V3 阶段 0：事实基线审计

审计日期：2026-08-06  
审计范围：`master` 分支当前源码（2.0.0-rc.1）  
目的：为 V3 工程投标资料证据化审查 Agent 改造建立事实基线，避免在虚假假设上设计。

## 1. 当前基础设施清单（已验证存在于源码）

### 1.1 认证与会话

- **源码位置**：`backend/app/services/security_service.py`、`backend/app/models/auth_session.py`、`backend/app/api/v2/auth.py`
- 会话令牌由 `secrets.token_urlsafe(48)` 生成 → `hash_token()` 计算 SHA256 → 以 `token_hash` 存入 `AuthSession` 表。这是**服务端持久化的随机不透明会话令牌**，不是 JWT。
- `AuthSession` 模型字段：`token_hash`（unique）、`csrf_token_hash`、`created_at`、`expires_at`、`last_seen_at`、`revoked_at`、`user_agent`、`ip_address`
- 注册、登录、登出、CSRF 双 cookie 保护（`csrf_token_hash` + `X-CSRF-Token` header）
- 密码哈希使用 Argon2（`argon2.PasswordHasher`），强度 ≥10 字符
- 登录限流（账号级别 `LOGIN_ACCOUNT_LIMIT`、IP 级别 `LOGIN_IP_LIMIT`、时间窗口 `AUTH_RATE_WINDOW_SECONDS`）
- 管理员创建邀请码（`IF-` 前缀 + `secrets.token_urlsafe(18)`）、角色管理
- 生产环境安全启动校验（`validate_production_security()`）
- **实际状态**：已在代码中实现，测试覆盖。

### 1.2 工作区隔离

- **源码位置**：`backend/app/models/workspace.py`、`backend/app/api/v2/workspaces.py`
- 每个用户可创建多个工作区，默认上限 20
- 文件、任务、报告均归属工作区
- 归档可恢复；永久删除需完整名称确认，不可恢复（历史软删除数据不会自动清理）
- **实际状态**：已在代码中实现，测试覆盖。当前无 `workspace_type` 字段区分 engineering/general。

### 1.3 文件上传与验证

- **源码位置**：`backend/app/services/file_service.py`、`backend/app/api/v2/workspace_files.py`
- 支持 `.csv`、`.xlsx`、`.pdf`、`.png`、`.jpg`、`.jpeg`、`.webp`、`.md`、`.markdown`
- 校验：扩展名白名单、MIME 类型、文件内容特征码、大小上限（默认 20MB）、用户配额（默认 200MB）
- 批量上传上限 10 个文件，工作区上限 50 个文件
- **实际状态**：已在代码中实现，测试覆盖。

### 1.4 文件理解

- **源码位置**：`backend/app/services/file_understanding_service.py`
- 对表格生成行列数、字段、类型、样本、缺失值、统计、日期范围
- 对 PDF 生成页数、是否有文本层
- 对图片生成尺寸、格式、OCR 预处理标记
- 对 Markdown 生成标题数、代码块数、链接数
- 版本化 Profile，支持角色建议、标签、解析器版本
- 用户可确认或修改角色和标签
- **实际状态**：已在代码中实现，文件理解接口为同步调用。

### 1.5 文件关系

- **源码位置**：`backend/app/services/file_relation_service.py`
- 基于字段名、标题、文件名、文档关键词和 OCR 特征生成候选关系
- 置信度阈值控制（`RELATION_MIN_CONFIDENCE`、`RELATION_HIGH_CONFIDENCE`）
- 用户可确认、拒绝和修正关系类型
- **实际状态**：已在代码中实现。

### 1.6 任务队列与状态机

- **源码位置**：`backend/app/services/task_queue_service.py`、`backend/app/services/task_state_machine.py`、`backend/app/models/task.py`
- SQLite 持久化队列（`Task` 模型 `status` 字段，`String(50)`，无数据库级 enum 约束）
- 完整任务状态机（`ALLOWED_TASK_TRANSITIONS`）：
  - `draft` — 任务草稿，可转为 `awaiting_clarification` / `planning` / `cancelled`
  - `awaiting_clarification` — 等待用户回答追问，可转为 `planning` / `cancelled` / `failed`
  - `planning` — Supervisor 生成计划中，可转为 `awaiting_clarification` / `awaiting_confirmation` / `failed` / `cancelled`
  - `awaiting_confirmation` — 等待用户确认计划，可转为 `planning` / `queued` / `cancelled`
  - `queued` — 已确认计划，等待 Worker 认领，可转为 `running` / `cancelled` / `failed`
  - `running` — Worker 执行中，可转为 `reviewing` / `retrying` / `completed` / `failed` / `cancelled`
  - `reviewing` — Quality Review Agent 审核中，可转为 `retrying` / `completed` / `completed_with_warnings` / `failed` / `cancelled`
  - `retrying` — 局部重试中，可转为 `queued` / `running` / `reviewing` / `failed` / `cancelled`
  - `completed` — 全部步骤通过，可转为 `retrying`（人工请求重跑）
  - `completed_with_warnings` — 通过但含警告，可转为 `retrying`
  - `failed` — 执行失败，可转为 `retrying`
  - `cancelled` — 已取消，终止状态，不可再转换
- 终端状态（`TERMINAL_TASK_STATUSES`）：`completed`、`completed_with_warnings`、`failed`、`cancelled`
- 支持协作式取消（`cancellation_requested_at` 字段，Worker 在可控检查点停止）
- 任务创建时最多两轮主动追问（`TASK_MAX_CLARIFICATION_ROUNDS`，默认 2）
- 版本化计划生成（`TaskPlan` 模型）、修改（`patch_plan`）和确认（`confirm_plan`）
- **实际状态**：已在代码中实现，测试覆盖。

### 1.7 独立 Worker

- **源码位置**：`backend/app/workers/task_worker.py`
- 单 Worker 轮询机制（`WORKER_POLL_INTERVAL_SECONDS` 默认 2s）
- 租约机制防重复执行（`WORKER_LEASE_SECONDS` 默认 120s）
- 心跳保活（`WORKER_HEARTBEAT_SECONDS` 默认 15s）
- 过期租约回收
- 受限局部重试（失败步骤重试，最多 `TASK_MAX_RETRIES` 次，默认 1）
- **实际状态**：已在代码中实现，测试覆盖。

### 1.8 SSE 实时事件

- **源码位置**：`backend/app/api/v2/workspace_tasks.py:341` — `/{task_id}/events/stream` 端点
- `stream_workspace_task_events()` 返回 `StreamingResponse`（`media_type="text/event-stream"`）
- SSE 推送任务步骤、工具调用、进度和错误
- 断线事件恢复（通过 `Last-Event-ID` header）
- 心跳保活（`task_event_heartbeat_seconds`，默认 15s）
- 检测到终端状态后自动关闭流
- 前端自动降级增量轮询（通过 `/{task_id}/events` 端点）
- **实际状态**：已在代码中实现。

### 1.9 报告与审计

项目包含三个报告相关服务，职责不同：

**`report_service.py`**（旧版/通用报告）
- `generate_task_report()`：基于 Task、ToolCall 和文件结果生成 Markdown 报告，写入 `REPORT_DIR`
- `get_task_report()` / `resolve_report_file()`：读取已有报告文件和路径解析
- 服务旧版 `/api/files` 和 V2 兼容路径

**`v2_report_service.py`**（V2 Agent 报告兼容入口）
- `generate_structured_report()`：Report Agent 的兼容入口
- 委托 `report_version_service.create_report_version()` 创建数据库版本化报告
- 保留 `_report_file()` 辅助函数用于 V2-04 测试和外部调用兼容

**`report_version_service.py`**（数据库版本化报告核心）
- `create_report_version()`：创建 `Report` 数据库记录，含版本号、模板 key、质量状态、Markdown 正文
- 多格式导出：Markdown、DOCX（python-docx）、PDF（PyMuPDF/fitz）
- `ReportAsset` 模型：资产引用清单（图表、附件），含存储 key 和内容哈希
- 版本历史上限：`REPORT_HISTORY_MAX_VERSIONS`（默认 10）
- 导出日限额：`REPORT_EXPORT_DAILY_LIMIT`（默认 50）
- 报告存储到 `REPORT_DIR`，资产路径通过 `resolve_asset_path()` 解析

**Quality Review（确定性质量审核）**
- **源码位置**：`backend/app/agents/v2_tools.py` → `run_quality_review()` / `_deterministic_review()`
- 确定性检查：失败步骤、未完成步骤、缺失数据结论、引用页码/片段校验、报告章节完整性、数字一致性、敏感信息泄露
- 可选 LLM 增强：仅在确定性通过且 `use_deepseek=true` 时调用模型进行语义审核
- 审核结果合并确定性发现和模型发现

- **实际状态**：三个报告服务均已在代码中实现，测试覆盖。

## 2. 五个专业 Agent 的实际职责和调用方式

### 2.1 Supervisor

- **源码位置**：`backend/app/agents/supervisor.py`
- 职责：接收确认后的计划，按步骤分配任务给专业 Agent
- 不直接执行工具调用
- 管理 Agent 步骤白名单（`ALLOWED_AGENT_STEPS`）
- 控制模型调用预算和工具调用预算

### 2.2 File Understanding Agent

- **源码位置**：`backend/app/agents/specialists.py`
- 职责：读取文件元数据、Profile、角色标签
- 工具：`workspace_context_lookup`
- 输入：文件 ID 列表

### 2.3 Data Analysis Agent

- **源码位置**：`backend/app/agents/specialists.py`
- 职责：执行 Pandas 多表分析
- 工具：`preset_multi_table_analysis`
- 参数：`generate_charts`（可选）

### 2.4 Document Research Agent

- **源码位置**：`backend/app/agents/specialists.py`
- 职责：对 PDF/Markdown 文档执行检索问答
- 工具：`selected_document_retrieval`
- 参数：`top_k`、`retrieval_mode`（默认 `auto`）

### 2.5 Report Agent

- **源码位置**：`backend/app/agents/specialists.py`
- 职责：基于所有步骤结果生成结构化报告
- 工具：`structured_markdown_report`

### 2.6 Quality Review Agent

- **Agent 定义**：`backend/app/agents/specialists.py` → `QualityReviewAgent`（`agent_type="quality_review_agent"`）
- **工具实现**：`backend/app/agents/v2_tools.py` → `run_quality_review()` / `_deterministic_review()`
- 职责：对报告执行确定性质量检查；可选 LLM 增强语义审核
- 工具：`deterministic_quality_review`（注册于 `tool_registry.py:141`）
- 确定性检查项：失败步骤、未完成步骤、缺失数据结论、引用页码/片段存在性、报告章节完整性、数字一致性、敏感信息泄露
- LLM 增强：仅在确定性通过且 `use_deepseek=true` 且模型预算 > 0 时调用，结果合并到确定性发现中
- Quality Review 必须是计划最后一步（`supervisor.py:211` 强制校验）

### 关键结论

- 五个 Agent 通过**工具注册表**（`tool_registry.py`）控制权限
- Agent 只能调用白名单工具，不能执行任意代码
- **不存在** Extraction Agent、Verification Agent、Engineering Review Agent
- Quality Review 是确定性规则检查（可选 LLM 增强），不包装成第 4 个 V3 节点

## 3. 当前 RAG 的真实算法

### 3.1 TF-IDF 检索（被错误标记为 `vector`）

- **源码位置**：`backend/app/services/vector_service.py`
- 实际算法：
  1. 分词（英文单词 + 中文字符 + 中文二元组）
  2. 构建文档频率（DF）
  3. 计算 TF-IDF 权重向量
  4. Cosine 相似度排序
  5. 返回 top-k 结果
- **这是纯 TF-IDF + Cosine 相似度，不是 Embedding 向量检索**
- **阶段 0 修正后**：返回 `retrieval_mode: "tfidf"`，不再返回 `"vector"`

### 3.2 关键词检索

- **源码位置**：`backend/app/services/rag_service.py` → `_search_keyword_chunks()`
- 精确子串匹配（+5 分）+ token 频次累加
- 返回 `retrieval_mode: "keyword"`

### 3.3 Auto 模式

- 优先尝试 TF-IDF，失败后回退关键词检索
- 修正后返回 `retrieval_mode: "tfidf"`（成功）或 `"keyword"`（回退）

### 3.4 为什么不是真实 Embedding 向量检索

1. `vector_service.py` 没有使用任何 Embedding 模型（无 `sentence-transformers`、无 `openai embeddings`）
2. 没有向量数据库索引（无 Chroma client、无 FAISS index、无 pgvector）
3. 检索在内存中逐 chunk 计算 TF-IDF，无持久化向量
4. `config.py` 中 `EMBEDDING_PROVIDER=local` 和 `VECTOR_STORE=chroma` **仅为规划配置项，代码中无对应实现**
5. `requirements.txt` 中无 `chromadb`、`faiss-cpu`、`sentence-transformers` 等依赖

## 4. 85 条 deterministic 评测实际验证了什么

### 4.1 数据集来源

- **源码位置**：`backend/app/evaluation/dataset.py`
- 数据集名称：`v2-core`，版本 `1.0`
- 分类：表格分析 15、多表对比 10、文档检索 15、跨源 10、OCR 5、需求澄清 10、拒答 10、报告完整性 10
- 资源：仅合成 CSV、Markdown 和扫描通知 SVG，不含真实用户文件

### 4.2 实际执行过程

- **源码位置**：`backend/app/evaluation/runner.py` → `_deterministic_execute()`
- 每个案例的"执行"实际上是：
  1. 读取预期的 `agents`、`tools`、`citations`、`refusal` 等 JSON 字段
  2. 直接返回这些预期值作为"实际结果"
- **不调用任何 LLM、OCR、真实检索或 Pandas**
- `_score_case()` 比较"预期值"与"自身"，形成自洽检查

### 4.3 实际验证的项目

| 检查项 | 实际含义 |
|--------|---------|
| `classification_correct` | 数据集的 `category` 字段和返回的 `classification` 字段一致（同源） |
| `clarification_correct` | 数据集的 `expect_clarification` 标记与返回一致（同源） |
| `plan_complete` | 只要数据集有预期 agents 或 refusal 或 clarification，就为 true |
| `tool_routing_correct` | 数据集的 `expected_tools` 与返回的 `tools` 列表完全一致（同源） |
| `citation_hit` | 数据集的 `expected_citations` 是返回 `citations` 的子集（同源） |
| `refusal_correct` | 数据集的 `expected_refusal` 与返回的 `refused` 一致（同源） |
| `numeric_consistency` | 相关类别始终返回 true（硬编码） |
| `quality_review_blocked` | 始终返回 false（硬编码） |

### 4.4 85 条评测**不能**证明什么

1. **不能证明模型质量**：从未调用 DeepSeek 或任何 LLM
2. **不能证明 OCR 准确率**：OCR 案例只检查资源引用，不执行 OCR
3. **不能证明检索准确率**：引用检查是同源数据比对，不是真实检索效果
4. **不能证明报告质量**：报告章节检查只是标记为 true
5. **不能证明 RAG 召回率**：无 Recall@K、MRR 等检索指标
6. **不能证明拒答安全性**：拒答案例的预期和实际来自同一数据源

### 结论

85 条 deterministic 通过 = **数据集加载、路由预期和持久化链路一致**，仅此而已。

## 5. MCP 当前是否真实实现

- **源码中零 MCP 代码**：无 `mcp` 包依赖、无 MCP Server、无 MCP Client
- 配置中无 MCP 相关环境变量
- `docs/MCP_PLAN.md` 明确声明"当前为规划，未接入正式 MCP Server"
- **结论**：MCP 未实现，为规划阶段。

## 6. DeepSeek 当前配置和验收状态

### 配置

- 模型名从 `DEEPSEEK_MODEL` 环境变量读取
- 默认值：`<部署时核实的可用模型名>`（占位符）
- 测试环境默认：`deepseek-v4-flash`（`conftest.py:17`）
- API Base URL：`https://api.deepseek.com/v1`
- 测试中 `LLM_ENABLED=false`，不发起实际调用

### 验收状态

- **未执行过真实 DeepSeek 质量评估**
- 未验证 API Key 有效性
- 未验证模型响应格式与代码兼容性
- 未测量实际延迟和成本
- 测试覆盖率基于确定性规则和 mock，不依赖 LLM 返回值

### 与 DeepSeek 官方文档一致性（截至 2026-08-06）

- 官方推荐的当前模型为 `deepseek-v4-pro` 和 `deepseek-v4-flash`
- 旧 `deepseek-chat`、`deepseek-reasoner` 已宣布停用
- 项目测试中使用 `deepseek-v4-flash` 与官方推荐一致
- 实施时需通过 `/models` API 核实实际可用模型名

## 7. V3 可以复用的基础设施

| 基础设施 | 复用方式 |
|----------|---------|
| 服务端会话令牌认证 + CSRF | 直接复用，无需修改 |
| 工作区模型 | 增加 `workspace_type` 字段后复用 |
| 文件上传与验证 | 直接复用，增加工程文件角色 |
| 文件关系服务 | 扩展关系类型后复用 |
| 任务队列 + Worker | 直接复用 |
| SSE 事件推送 | 直接复用 |
| 报告存储与导出 | 扩展报告模板后复用 |
| Tool Registry 权限控制 | 扩展工程审查工具后复用 |
| Supervisor 调度框架 | 重写为 Extractor/Verifier/Reporter 三个节点 |
| 确定性 Quality Review | 扩展为结论—证据—规则质量门 |
| 评测框架（runner + dataset） | 扩展为 `engineering-review-v1` 数据集 |
| 安全配置校验 | 直接复用 `validate_production_security()` |
| Docker Compose 部署 | 扩展后复用 |

## 8. V3 尚缺少的能力

### 8.1 垂直数据模型

- `Evidence` 表（证据定位：页码/单元格/chunk + 引用片段 + 内容哈希）
- `ReviewRule` 表（规则元数据 + YAML 加载校验）
- `ReviewFinding` 表（问题清单：严重度 + 结论 + 规则/证据绑定 + 复核状态）
- `workspace_type` 字段（engineering / general）

### 8.2 证据结构

- PDF 页码定位（`locator_type: pdf_page`）
- 电子表格单元格定位（`locator_type: spreadsheet_cell`）
- 文本块定位（`locator_type: text_chunk`）
- 内容哈希去重与校验

### 8.3 规则引擎

- 规则 YAML 版本化管理
- 规则类型：`required_field`、`cross_file_equal`、`numeric_threshold`、`date_order`、`document_presence`、`evidence_required`
- Pydantic 校验 + 规则快照

### 8.4 真实检索

- BM25 关键词检索（精确匹配编号、证书号、条款号）
- Embedding 语义检索（BGE-M3 或其他中文模型）
- 混合检索 + Reciprocal Rank Fusion
- 持久化向量索引
- Recall@K、MRR、引用正确率、P95 延迟指标

### 8.5 效果评测

- 工程审查专用评测集（1 套黄金项目 + 4~6 套变体）
- 30~50 条检索查询 + 已标注相关文档
- 80 个以上已标注抽取字段
- 30 个以上已标注问题
- 故障注入案例

### 8.6 MCP Server

- Review Tools MCP Server（`search_review_rules`、`run_bid_consistency_checks`）
- MCP Client 工具发现与调用
- 暂时故障 → 局部重试 → 人工处理链路

## 9. 当前产品表述与源码的一致性检查

| 表述来源 | 表述内容 | 源码验证 | 一致性 |
|----------|---------|---------|--------|
| AGENTS.md | 技术栈含 Chroma/FAISS | 无 Chroma/FAISS 代码 | ⚠️ 规划项，非已实现 |
| README.md | RAG 使用 TF-IDF | `vector_service.py` 确为 TF-IDF | ✅ 一致 |
| README.md | deterministic 是规则自检 | `runner.py` 确为自洽检查 | ✅ 一致 |
| README.md | 未执行 DeepSeek 验收 | 测试 `LLM_ENABLED=false` | ✅ 一致 |
| .env.example | `VECTOR_STORE=chroma` | 无 Chroma 客户端代码 | ⚠️ 仅为规划占位 |
| config.py | 同上 | 同上 | ⚠️ 仅为规划占位 |
| EVALUATION.md | "向量检索"描述 | 实际为 TF-IDF | ⚠️ 阶段 0 已修正 |
| rag_service.py | `retrieval_mode: "vector"` | 实际执行 TF-IDF | ❌ 阶段 0 已修正 |

## 10. V2 通用文档分析冻结基线声明

当前 V2 主线代码（2.0.0-rc.1）将作为 `general` 区域的冻结基线：

- **功能范围**：通用文档上传、多格式理解、文件关系发现、Pandas 数据分析、PDF TF-IDF 检索、图片 OCR、Markdown 报告生成
- **五个 Agent**：File Understanding、Data Analysis、Document Research、Report、Quality Review
- **不新增功能**：V3 开发期间，`general` 区域只修复严重缺陷，不横向扩展
- **不删除旧 API**：所有 V2 API、Agent、评测数据保持不变
- **不迁移数据**：已有工作区和任务数据保持原样
- **后续分区**：阶段 1 将增加 `workspace_type` 字段，旧数据为 `general`，新建工程项目为 `engineering`

## 11. 审计结论

1. **项目已达到 2.0.0-rc.1 发布候选质量**，认证、工作区、上传、队列、Worker、SSE、报告和审计基础设施均可工作。
2. **五个专业 Agent 通过工具注册表执行**，安全边界明确，不执行任意代码。
3. **RAG 是 TF-IDF + 关键词检索**，不是 Embedding 向量检索。阶段 0 已修正命名。
4. **85 条 deterministic 评测是规则自检**，不代表模型、OCR、检索或报告质量。
5. **MCP 未实现**，为规划阶段。
6. **DeepSeek 模型名从环境变量读取**，未执行真实验收。
7. **Chroma/FAISS/Embedding 仅为配置占位**，无对应代码实现。
8. **V3 可复用大部分基础设施**，但缺少垂直数据模型、证据结构、规则引擎、混合检索和效果评测体系。
