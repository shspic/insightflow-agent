# InsightFlow Agent 简历材料

## 项目名称

InsightFlow Agent：多模态文档与数据分析智能体

## 一句话项目描述

基于 FastAPI + React 构建的多模态资料分析与工程投标审查平台，通过确定性审查管道、DeepSeek 核验、MCP 工具、混合检索、四节点 Supervisor 和质量门控生成证据可追溯报告，并保留 V2 通用文件分析、Worker、SSE 与报告能力。

## 简历项目描述（标准版）

InsightFlow Agent 是一个前后端分离的多模态资料分析与工程审查平台。V3 主线先对投标材料做确定性抽取和六类规则检查，再由 DeepSeek Verification 规划固定 MCP 工具与 BM25+BGE+RRF 混合检索，四节点 Supervisor 按 extraction、verification、quality_review、reporting 推进，Quality Gate 复核来源哈希、locator 与输入快照后才生成 Markdown/PDF 报告。V2 兼容线保留五类文件理解、Pandas 分析、数据库任务队列、独立 Worker、SSE、OCR 和三格式报告。系统使用 Session Cookie、CSRF、邀请码与工作区隔离，并通过 Docker Compose + Nginx 完成单机 HTTPS 公网部署。V3 主链是受控确定性状态机，不应写成 LangGraph 多 Agent 主链。

## 简历 Bullet

- 基于 FastAPI + React 构建全栈多用户 Agent 平台，实现 Argon2id 密码认证、邀请码注册、Session Cookie + 双 Token CSRF 防护、工作区级数据隔离和完整权限依赖校验。
- 设计确定性 Review Pipeline 与四节点 Supervisor，结合 DeepSeek Verification、MCP 工具和 Quality Gate，对 Evidence 哈希、来源文件、locator 与 input snapshot 进行复核，阻止无来源结论进入报告。
- 构建 BM25+BGE+RRF 混合检索和人工候选采纳边界，真实评测 overall recall@3=0.7632、recall@5=0.8553，并如实保留 validation recall@3 与 no-answer 误召回不足。
- 保留 V2 数据库任务队列、独立 Worker、租约/心跳、SSE、协作式取消、五类文件理解、Pandas/OCR 和三格式报告，用受控流程而非自主多 Agent 包装业务链路。
- 使用 GitHub Actions、Playwright、Docker Compose 与 Nginx 完成测试、构建和单机 HTTPS 公网部署；不声称高并发、高可用或备案完成。

## 技术关键词

- 前端：React、Vite、React Router、Axios、CSS Variables 设计 Token、浅色/深色/跟随系统主题、响应式（360px-1440px）、基础无障碍、SSE EventSource。
- 后端：FastAPI、Uvicorn、Pydantic、REST API、模块化 service 层、Alembic 数据库迁移、SQLAlchemy ORM。
- Agent/工作流：确定性 Review Pipeline、Verification Agent、Streamable HTTP MCP、四节点 Supervisor、Quality Gate；V2 兼容线保留 Supervisor + 5 个专业步骤，V3 主链不使用 LangGraph。
- 认证与安全：Argon2id、Session Cookie（HttpOnly/Secure/SameSite=Lax）、双 Token CSRF、邀请码哈希存储、密码强制修改、持久化限流、资源归属双重校验。
- 文件理解：CSV/XLSX/PDF/PNG+JPG+WEBP/Markdown 五类、多工作表 Excel、分页 PDF、扫描 OCR、版本化 Profile、角色/标签/关系候选确认。
- 数据分析：Pandas、openpyxl、缺失值/重复值/分布/分组/连接/对比/趋势、Cross-join 风险检测、预设 Matplotlib 图表。
- RAG：V3 使用 BM25+BGE+RRF 混合检索、确定性 Corpus 与 Evidence 哈希/locator 校验；V2 兼容线保留关键词/TF-IDF 检索。
- OCR：pytesseract、Pillow、Tesseract 中英文、低文本页检测、OCR 警告标记。
- 报告：Markdown/DOCX/PDF 三格式、三模板、版本管理、用户反馈、鉴权下载、python-docx。
- 工程化：SQLite WAL + busy timeout + 外键、Docker、Docker Compose、Nginx 反向代理、非 root 运行、生产安全门禁、`.env.example`、pip check、compileall。
- 运维：PowerShell/Bash 部署脚本、systemd timer、logrotate、备份/恢复/升级/回滚/清理/健康检查、隔离验收环境。

## 简历版本

### 保守版

InsightFlow Agent：基于 FastAPI + React 的全栈多用户资料分析与工程审查平台，实现认证与工作区隔离、确定性材料抽取和规则检查、受控 Verification Agent、数据库任务队列 + Worker、SSE 实时进度、结构化报告与多格式导出，并通过 Docker Compose + Nginx 完成单机 HTTPS 公网部署。

适合强调：后端开发、全栈开发、文件处理、数据分析工具。

### 标准版

InsightFlow Agent：基于 FastAPI + React 构建的多用户资料分析与工程投标审查平台。V3 主线通过确定性 Review Pipeline、DeepSeek Verification、Streamable HTTP MCP、BM25+BGE+RRF 混合检索、四节点 Supervisor 和 Quality Gate 生成证据可追溯的报告；V2 兼容线保留五类文件理解、数据库任务队列、独立 Worker、SSE、图表和 Markdown/DOCX/PDF 导出。系统已完成 Docker Compose + Nginx 单机 HTTPS 公网部署。

适合强调：AI 应用开发、AI Agent 开发、RAG 应用开发。

### 强化版

InsightFlow Agent：独立设计并实现一个面向多用户的多模态资料分析与工程投标审查平台。从零搭建 FastAPI + React 前后端闭环，以确定性 Review Pipeline、DeepSeek Verification、Streamable HTTP MCP、BM25+BGE+RRF 混合检索、四节点 Supervisor 和 Quality Gate 形成证据可追溯的审查报告链路；保留 V2 工作区、五类文件理解、数据库任务队列、Worker、SSE 与三格式报告能力。项目已完成单机 HTTPS 公网部署；当前后端收集 959 项、最近完整成功基线 791 passed，前端 116 passed，不能写成“959 项全部通过”。

适合强调：AI Agent 工程化、工具调用编排、端到端项目交付能力。

## 面试时 1 分钟介绍话术

InsightFlow Agent 是我做的一个多用户多模态资料分析与工程审查平台，当前版本为 `3.0.2`。它不是普通聊天机器人，而是把确定性审查、模型核验、工具调用、证据门控和报告交付串起来的任务执行系统。

在 V3 主线里，用户上传招标要求、响应文件和人员、设备、资质、澄清等材料。系统先做确定性抽取与六类规则检查，再由 Verification Agent 在预检边界内规划固定 MCP 工具，结合 BM25+BGE+RRF 检索核验证据。候选结论由用户确认后，四节点 Supervisor 按抽取、核验、质量审查和报告生成推进，Quality Gate 对来源哈希、定位信息和输入快照做最终校验。

V2 兼容线则保留 CSV、Excel、PDF、图片和 Markdown 的通用分析流程：任务计划落库后由独立 Worker 执行，前端通过 SSE 展示进度，最终生成带引用、图表和限制说明的 Markdown、DOCX、PDF 报告。两条链路共用认证、工作区隔离、配额、监控与备份能力，并通过 Docker Compose + Nginx 对外提供 HTTPS 服务。

当前版本为 `3.0.2`，已完成单机 HTTPS 公网部署。后端当前收集 959 项但本轮全量未完成，最近完整成功基线为 791 passed；前端 116 passed。真实 DeepSeek+BGE+MCP 评测已完成，但验证集检索和 no-answer 误召回仍需优化。

## 这个项目为什么是 Agent？

它具备任务型 Agent 的核心特征，但更准确的说法是**受控的工作流型 Agent**：

- 确定性程序负责材料抽取、规则判断、权限、状态迁移和持久化，模型不接管整条业务链；
- Verification Agent 只在预检通过后选择固定 MCP 工具，并使用混合检索核验证据；
- 四节点 Supervisor 通过结构化状态推进流程，节点职责和终止条件由代码约束；
- Quality Gate 在交付前检查证据来源、定位信息和输入快照，不满足条件就阻止报告生成；
- 模型调用、工具调用和重试次数有明确上限，关键候选结论保留人工确认；
- V2 的 Supervisor + 五个专业步骤属于兼容线，不能描述为 V3 的自主多 Agent 主链。

它不是为了“自由聊天”，而是为了在确定性约束下把分散材料变成可核验报告。

## 为什么从单 Agent 改成 Supervisor + 子 Agent？

V1 使用 LangGraph 固定线性工作流：分类、计划、路由、工具执行、结果整理、保存。这个架构在单文件、单任务类型时能跑通，但存在几个问题：

1. 任务类型判断和工具选择耦合在同一个线性流程里，多文件综合分析需要硬编码分组逻辑；
2. 没有追问能力——Supervisor 发现信息不足时无法停下来让用户补充，只能按不足信息继续执行；
3. 计划无法让用户确认修改——V1 的计划生成和执行在同一请求里完成，用户只能接受最终结果；
4. 没有独立的质量审核环节——报告中没有数字校验、引用验证和自动修复机制。

V2 把线性工作流拆成 Supervisor + 五个专业 Agent，核心收益是：Supervisor 专门解决"做什么、怎么分、信息够不够"，五个子 Agent 各自负责专业执行，Quality Review Agent 在报告交付前进行独立校验。Agent 之间通过结构化状态通信，边界清晰，出问题时可以定位到具体 Agent 和步骤。

## 子 Agent 如何划分？

五个专业 Agent 按职责边界划分：

1. **File Understanding Agent**：负责理解文件内容，生成摘要、角色建议、标签和文件间关系候选。输入是文件元数据和确定性解析结果，输出是受 schema 约束的 Profile、角色和关系候选（含置信度和证据）。不分析数据、不写报告。

2. **Data Analysis Agent**：负责表格数据的确定性统计和分析。输入是经过确认的表格文件和用户分析目标，输出是结构化统计结果、数据质量问题、图表规格和计算说明。不解释 PDF 规则，不写报告。

3. **Document Research Agent**：负责 PDF/Markdown 文档的事实检索。输入是研究子任务和分块文本，输出是事实列表和带页码/章节的引用。不计算表格数字，不生成报告。

4. **Report Agent**：负责把所有 Agent 的输出综合为结构化报告。输入是计划、分析结果、文档事实、图表引用和审核反馈，输出是统一中间结构（可渲染为 Markdown/DOCX/PDF）。不重新计算数字，不编造引用。

5. **Quality Review Agent**：负责交付前质量审核。检查报告结构完整性、数字一致性、引用有效性、计划完成度；发现问题时给出重试指令，最多允许两轮审核和受限自动修复。

## 为什么工具不是 Agent？

OCR、文件解析（PyMuPDF/openpyxl）、图表生成（Matplotlib）、DOCX/PDF 导出（python-docx）有明确输入、确定性接口和可校验输出，没有独立目标、长期上下文或决策收益。把它们包装成 Agent 会额外引入 Prompt、状态同步、重试和模型成本，却不能提高结果质量。

因此：
- Agent 决定"是否需要 OCR、解析哪份文件、生成什么图表"；
- 工具负责"按受控参数执行并返回结构化结果"；
- 确定性编排器负责权限、超时、幂等、状态和错误。

## 如何避免无限循环？

系统使用多层防护：

1. 追问最多 2 轮，每轮最多 3 个问题；
2. Supervisor 计划生成最多 2 次（初稿一次、用户修改后重整一次）；
3. 每个专业 Agent 每个步骤默认 1 次模型调用，语义修订最多 1 次；
4. 单步骤自动重试最多 1 次，单任务自动重试步骤总数最多 2 个；
5. Quality Review 最多 2 轮，第二轮后仍不通过则标记 `completed` 并记录质量警告，不再循环；
6. 标准任务模型调用总上限 12 次；
7. 所有预算写入执行快照，确定性代码在每次模型调用前后检查。

## 计划确认的意义？

计划确认是 V2 的核心安全机制之一。其意义在于：

- 用户在正式执行前可以看到系统将使用哪些文件、做哪些步骤、预期产出什么；
- 用户可以修改文件选择、分析范围、输出重点和步骤启用状态，或直接取消；
- 避免模型误判任务意图后，在用户不知情的情况下完成错误分析并产生模型费用；
- 计划版本化保存，用户确认记录和修改历史全部可审计；
- 从计划重新执行时固定原计划版本和输入文件快照，保证可复现。

## 数据库队列为什么不用 Celery？

项目针对 5 人以内低并发场景，使用 Celery 会引入以下代价：

- 需要额外部署消息中间件（Redis/RabbitMQ），增加部署运维复杂度；
- Celery 的进程模型、序列化、并发配置和 Windows 兼容性对当前单机场景过于复杂；
- 数据库队列（使用任务表中的 `available_at`、`lease_owner`、`lease_expires_at` 和租约机制）在低并发时足够可靠：独立 Worker 轮询领取，租约到期后可被重新领取，崩溃不丢任务；
- 业务层通过队列接口抽象，未来切换到专业队列后端时不需要改业务代码。

## SQLite 单 Worker 的适用边界？

适用条件：约 5 人以内、并发写入低、任务可按队列顺序执行、单机部署。

不适用场景：
- 多机多实例并发写——SQLite 不支持网络并发写；
- 高频繁并发——SQLite 写锁是库级锁；
- 需要专业队列特性（消息优先级、延迟消息、死信队列）。

在适用边界内，SQLite + WAL + busy timeout + 单 Worker 的可靠性足够。超过边界时应迁移到 PostgreSQL + 专业队列后端。

## SSE 如何恢复？

SSE 连接断开后，前端使用以下机制恢复：

1. 浏览器原生 EventSource 自动重连，携带 `Last-Event-ID` 请求头；
2. 后端收到 `Last-Event-ID` 后，从数据库 `task_events` 表查询该 ID 之后的事件并补推；
3. 如果 SSE 不可用（某些代理或网络环境），前端自动降级到 2-5 秒增量轮询，通过 `after_id` 查询增量事件；
4. 任务到达终态（`completed`/`failed`/`cancelled`）后，前端清理 EventSource 和定时器。

## 取消为什么是协作式？

取消流程：

1. 用户调用取消接口，数据库写入 `cancel_requested_at` 和 `cancel_requested_by`；
2. 等待中的任务（draft/awaiting_clarification/awaiting_confirmation/queued）可立即状态迁移为 cancelled；
3. 正在执行中的任务，Worker 在步骤开始前、工具调用前后、文件循环和模型调用后检查取消标记；
4. 已发出的外部 HTTP 调用（如 DeepSeek API）无法强制终止——只能依靠请求超时或 API 客户端支持的取消。

因此取消是"协作式"：Worker 在确定性的检查点主动响应取消标记，但不能承诺瞬时中断所有外部调用。这不是设计缺陷，而是分布式系统的基本原则——已发出到外部服务的网络请求无法从客户端强制撤销。

## 局部重试如何工作？

局部重试以失败 `task_step` 为单位：

1. 失败步骤创建新 attempt，`retry_of_step_id` 指向上次失败的 step；
2. 复用未失效的上游步骤结果（数据库已持久化的产物引用）；
3. 当前步骤及依赖其输出的下游步骤标记为待重新计算；
4. 工具使用幂等键（`idempotency_key`），避免重复生成图表/资产；
5. Quality Review 发现可修复问题时，触发目标步骤重试，最多重试 2 个不同步骤。

## 文件关系为什么需要用户确认？

文件关系（如"这两张表可以按某列连接"、"这个 Excel 受这份 PDF 规则约束"）直接影响后续分析的正确性。如果连接键错误，全部合并、对比和汇总结果都会失真。系统通过规则和模型生成关系候选（含置信度和证据），但：

- confidence 是启发式阈值不是真实概率；
- 模型可能误判字段含义；
- 涉及连接键、覆盖更新、规则约束的关系，即使高置信也必须由用户确认后才能进入正式计划。

低置信度关系默认不参与自动分析，用户可以在"更多候选"中查看并手动启用。

## RAG 如何保证引用？

检索流程：

1. PDF 上传后 PyMuPDF 按页提取文本，按页/段落切分为 chunk，保存 `file_chunks` 表（含页码、块序号、字符范围）；
2. V2 通用线使用关键词/TF-IDF；V3 工程审查线使用 BM25+BGE+RRF 混合检索，返回带 locator、来源哈希和文件归属的候选证据；
3. Document Research Agent 基于检索片段生成事实时，每条事实必须附带 `citation_id`、文件 ID、页码/块 ID；
4. Report Agent 使用引用 ID 生成脚注，确定性代码校验每个引用 ID 是否可解析到真实的 chunk 记录；
5. Quality Review Agent 检查引用覆盖率和引用存在性。

当前 V3 主线已使用真实 BGE 稠密检索与 BM25 融合；引用可靠性仍不依赖模型承诺，而依赖服务端对引用 ID、locator、内容哈希、来源文件哈希和 input snapshot 的确定性复核。关键词/TF-IDF 只代表 V2 兼容线。

## Quality Review 如何防止数字和引用错误？

Quality Review Agent 执行以下检查：

1. 报告结构完整性：必填章节是否存在；
2. 数字一致性：报告中引用的数字与上游工具输出逐项比对；
3. 引用有效性：每个引用 ID 是否可解析到真实的文件/chunk 记录；
4. 引用覆盖性：关键陈述是否有对应引用支撑；
5. 计划完成度：计划中要求的步骤是否全部完成；
6. 资产存在性：引用图表的资产文件是否存在；
7. 语义一致性：使用 DeepSeek 检查报告叙述是否与证据一致。

可自动修复的问题（如报告缺少某章节但上游数据存在、数字与工具结果不符）触发目标步骤重试。不可自动修复的问题（如需要用户确认连接键、文件损坏）标记为警告并交付。

## DeepSeek 不可用如何降级？

系统设计了三层降级策略：

1. 确定性功能（文件解析、Pandas 分析、图表生成、OCR、报告模板渲染）完全不依赖 DeepSeek，即使 DeepSeek 完全不可用也能输出结构化结果；
2. DeepSeek 调用有连接超时、读取超时和最大重试；失败时不阻塞整个任务，而是记录降级标记并继续；
3. deterministic 评估集（85 条）完全不调用 DeepSeek，通过规则路由验证系统的非 LLM 部分是否正确工作。

旧模型名（如代码中残留的旧模型标识）触发 degraded readiness 但不会伪装成成功。生产环境通过 `DEEPSEEK_MODEL_DEFAULT` 和 `DEEPSEEK_MODELS_AVAILABLE` 环境变量配置具体模型名。

## 用户数据如何隔离？

每一层都做归属校验：

- 工作区查询：`workspace.owner_user_id = current_user.id`；
- 文件操作：`file.owner_user_id = current_user.id AND workspace_file.workspace_id = requested_workspace_id`；
- 任务/报告/下载/SSE/取消/重试：逐级校验 task.owner_user_id、workspace.owner_user_id；
- 管理员默认不返回普通用户报告正文、文件内容和未脱敏模型输入。

依赖层提供 `get_current_user`、`require_active_user`、`require_admin`、`get_owned_workspace`、`get_workspace_file` 等可复用依赖，避免每个路由函数手写校验。

## Session Cookie 和 CSRF 机制？

认证使用服务端不透明 Session Token：

- 登录成功生成高熵随机 token（`secrets.token_urlsafe`）；
- 数据库只保存 `token_hash`（SHA-256），不保存明文；
- 浏览器通过 `HttpOnly`、`Secure`（生产）、`SameSite=Lax` Cookie 携带；
- 修改密码、管理员重置、账号停用时撤销所有 Session；
- 不把认证 token 放入 `localStorage` 或 `sessionStorage`。

CSRF 使用双 Token 模式：除 Session Cookie 外，服务端下发一个可读的 CSRF Token，前端在状态变更请求中通过自定义 Header 回传，后端逐请求校验。

## 报告版本和三格式导出？

- 任务完成后自动生成初始报告（version 1）；
- 用户选择新模板、提交纠错反馈或修改参数后，系统生成递增版本的新报告；
- 旧版本保留，可查看历史版本和变更摘要；
- 三格式导出：Markdown（直接返回）、DOCX（python-docx 生成）、PDF（Markdown 经渲染引擎转换）；
- 导出文件作为 `report_assets` 保存，通过鉴权下载接口获取，不暴露服务器路径。

## 配额和监控系统？

配额系统：

- 用户级：存储量、单文件大小、单次上传文件数、每日任务数、并发任务数；
- 管理员免普通配额，不免系统级安全上限；
- 服务端在 API 层逐请求检查，不依赖前端。

监控系统分四层：

1. Worker 级别：运行状态、当前任务、心跳、租约；
2. Agent 级别：任务总数、成功/失败/取消数、平均耗时；
3. 工具级别：调用总数、成功/失败、平均耗时；
4. 模型级别：调用次数、Token 用量、错误率。

三层健康检查：`/api/health`（浅层）、`/api/health/readiness`（含数据库）、`/api/health/live`（含 Worker 心跳）。

## deterministic 评估代表什么？

deterministic 评估包含 85 条合成测试用例，覆盖文件解析、任务意图分类、工具路由、文件角色建议和报告模板选择。

**它明确不代表 DeepSeek 模型准确率。**

它是确定性规则与预期路由的自检：验证系统的非 LLM 部分（文件类型判断、工具选择、角色推断规则、报告模板匹配）是否按设计工作。当前结果 `task_success_rate=1.0`、平均响应 1ms，说明确定性路由全部命中——这验证了代码正确性，但不能声称模型表现好。

评估集完全不调用 DeepSeek。真实模型效果需要在公网部署后，使用真实 DeepSeek 进行端到端人工评估。

## 国内部署方案？

生产部署使用 Docker Compose + Nginx 同域方案：

- `web`：Nginx + React 静态产物，发布 80/443，反代 `/api` 到 backend；
- `backend`：单 Uvicorn 进程，只在内部网络提供 8000；
- `worker`：独立单 Worker 进程，共享 SQLite 和 storage 持久卷；
- Nginx 配置 SSE 无缓冲、SPA fallback、静态缓存、gzip、安全头、上传大小限制；
- SQLite 开启 WAL、busy timeout、外键约束、连接 pre-ping/recycle；
- 容器以非 root 用户 (UID 10001) 运行，根文件系统只读；
- 包含全套运维脚本：首次部署、备份/恢复、升级、回滚、清理、健康检查。

部署文档在 `docs/V2_07_*.md`，运维脚本在 `deploy/scripts/`。

## 历史演示环境是什么？

V1 时期曾使用 Vercel 部署前端、Render 部署后端作为公网演示。那个部署存在以下限制：

- Render 免费服务冷启动慢，首次访问需等待；
- Render 免费 Web Service 文件系统不可持久保存 SQLite 和上传文件；
- OCR 依赖 Tesseract，Render 环境不一定可用；
- 不支持多用户认证和工作区隔离。

V2 正式部署方案已完全替代为国内单机 Docker Compose 方案。Vercel/Render 地址不再作为 V2 正式地址，仅在项目历史中进行说明。

## 当前最大限制？

当前已知限制：

1. 已完成单机 HTTPS 公网部署，但尚无域名、ICP/公安备案，公共发布开关仍为 false；
2. 公网匿名页面已验收，登录后的完整业务链尚未形成当前发布版本的线上自动化记录；
3. 已完成真实 DeepSeek+BGE+MCP 评测，但验证集检索与 no-answer 误召回仍未达到理想目标，不能声称高准确率；
4. SQLite 单 Worker 只适合低并发，不支持多实例高可用；
5. 文件理解仍有同步 HTTP 路径，未支持任意 Agent 节点暂停/恢复，也不能强制终止已经发出的外部调用；
6. V3 工程审查使用 BM25+BGE+RRF 混合检索；关键词/TF-IDF 是 V2 历史链路，不能代表当前主线；
7. 未迁移 PostgreSQL、对象存储或专业队列，单机部署没有高可用与故障切换验证；
8. 当前 Git Tag 为 `v3.0.2`，但匿名线上接口没有暴露 build version，线上 commit 对应关系仍需发布标识证明。

## 代码是否由 AI 辅助？

诚实回答：在开发中使用了 AI 编程助手提高效率。但我负责：

- 需求拆解和阶段划分（V2-01 到 V2-08 的实施顺序和边界）；
- 关键架构决策（Supervisor + 子 Agent 的职责划分、数据库队列 vs Celery 的取舍、取消/重试的语义设计、文件关系的用户确认机制）；
- 每一阶段的验证标准制定和实际测试执行；
- 调试和排错（CORS、CSRF、Tesseract 环境、Docker 构建、Pandas 未来警告、datetime.utcnow 弃用）；
- 文档整理和面试材料撰写。

AI 编程助手是工具，项目架构、取舍、验证和交付由我把控。

## 本人在项目中的真实职责

我负责从需求分析、架构设计、数据库迁移、后端 API、受控工作流、RAG、MCP、OCR、文件处理、报告系统、前端页面、Docker 部署、运维脚本到文档整理的端到端实现。每个阶段限定范围、先验证再推进；当前后端收集 959 项、最近完整成功基线 791 passed，前端 116 passed，并完成真实评测、浏览器证据和单机公网部署。

项目的重点是工程闭环：不是单点算法或某个模型的效果，而是从用户注册到最终报告交付的完整系统。

## V2 适合岗位

- AI 应用开发 实习/初级
- AI Agent 开发 实习/初级
- Python 后端开发 实习/初级
- 全栈 AI 应用开发 实习/初级
- RAG 应用开发 实习/初级
