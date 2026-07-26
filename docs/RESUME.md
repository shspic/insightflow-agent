# InsightFlow Agent 简历材料

## 项目名称

InsightFlow Agent：多模态文档与数据分析智能体

## 一句话项目描述

基于 FastAPI + React + LangGraph 构建的多模态文档与数据分析 Agent 平台，实现 Supervisor + 五个专业 Agent、多格式文件理解、计划确认、数据库任务队列、SSE 实时进度、报告版本管理和 Docker 生产部署。

## 简历项目描述（标准版）

InsightFlow Agent 是一个前后端分离的多模态文档与数据分析 Agent 平台。后端基于 FastAPI + SQLAlchemy + SQLite + Alembic 构建，前端基于 React + Vite。系统实现 Argon2id 密码认证、邀请码注册、Session Cookie + 双 Token CSRF 和工作区级数据隔离；支持五类文件（CSV/XLSX/PDF/PNG+JPG+WEBP/Markdown）的统一解析、Profile、角色/标签建议和文件关系候选确认；Supervisor 主动追问与版本化计划确认后，由独立 Worker 通过数据库任务队列领取执行，前端通过 SSE 展示实时进度（支持 Last-Event-ID 断线恢复和轮询降级）；LangGraph 编排 Supervisor + File Understanding / Data Analysis / Document Research / Report / Quality Review 五个专业 Agent，Tool Registry 和 Prompt Registry 统一管理工具与 Prompt 版本；集成 Pandas、Matplotlib、PyMuPDF、Tesseract OCR、轻量 RAG 检索，实现多工作表 Excel 分析、PDF 分页检索、扫描 PDF OCR 和 Markdown/DOCX/PDF 三格式报告导出；内置报告版本管理、三模板、用户反馈、配额/监控/评估/备份系统；通过 Docker Compose (Nginx + Backend + Worker) 完成国内单机同域生产部署包。

## 简历 Bullet

- 基于 FastAPI + React 构建全栈多用户 Agent 平台，实现 Argon2id 密码认证、邀请码注册、Session Cookie + 双 Token CSRF 防护、工作区级数据隔离和完整权限依赖校验。
- 使用 LangGraph 编排 Supervisor + 5 个专业 Agent（File Understanding / Data Analysis / Document Research / Report / Quality Review），设计 Tool Registry 和 Prompt Registry 统一管理工具与版本，限制循环和模型调用上限防止失控。
- 集成 Pandas、Matplotlib、PyMuPDF、Tesseract OCR 和轻量 RAG，实现多工作表 Excel 分析、PDF 分页检索与引用、扫描页 OCR、Cross-join 检测、Markdown/DOCX/PDF 三格式报告导出。
- 设计数据库任务队列 + 独立 Worker + 租约/心跳 + SSE 实时进度（Last-Event-ID 断线恢复与轮询降级）+ 协作式取消 + 失败步骤局部重试 + Quality Review 自动修复，保证任务可靠执行。
- 实现报告版本管理、三模板（综合分析/学生调研/岗位分析）、用户反馈闭环、集中配额系统、Worker/Agent/工具/模型四层指标监控、85 条 deterministic 评估集、SQLite 备份/恢复/清理和 Docker Compose 生产部署（Nginx 同域反代 + HTTPS + SPA fallback）。

## 技术关键词

- 前端：React、Vite、React Router、Axios、CSS Variables 设计 Token、浅色/深色/跟随系统主题、响应式（360px-1440px）、基础无障碍、SSE EventSource。
- 后端：FastAPI、Uvicorn、Pydantic、REST API、模块化 service 层、Alembic 数据库迁移、SQLAlchemy ORM。
- Agent：LangGraph、Supervisor + 5 专业 Agent、版本化 AgentState、Tool Registry、Prompt Registry、循环/调用上限、deterministic 编排器。
- 认证与安全：Argon2id、Session Cookie（HttpOnly/Secure/SameSite=Lax）、双 Token CSRF、邀请码哈希存储、密码强制修改、持久化限流、资源归属双重校验。
- 文件理解：CSV/XLSX/PDF/PNG+JPG+WEBP/Markdown 五类、多工作表 Excel、分页 PDF、扫描 OCR、版本化 Profile、角色/标签/关系候选确认。
- 数据分析：Pandas、openpyxl、缺失值/重复值/分布/分组/连接/对比/趋势、Cross-join 风险检测、预设 Matplotlib 图表。
- RAG：PyMuPDF 分页提取、PDF/Markdown chunk 分块、关键词/TF-IDF 检索、章节/页码引用、扫描 PDF OCR。
- OCR：pytesseract、Pillow、Tesseract 中英文、低文本页检测、OCR 警告标记。
- 报告：Markdown/DOCX/PDF 三格式、三模板、版本管理、用户反馈、鉴权下载、python-docx。
- 工程化：SQLite WAL + busy timeout + 外键、Docker、Docker Compose、Nginx 反向代理、非 root 运行、生产安全门禁、`.env.example`、pip check、compileall。
- 运维：PowerShell/Bash 部署脚本、systemd timer、logrotate、备份/恢复/升级/回滚/清理/健康检查、隔离验收环境。

## 简历版本

### 保守版

InsightFlow Agent：基于 FastAPI + React 的全栈多用户文档分析平台，实现用户认证、工作区隔离、五类文件上传/解析/Profile、数据库任务队列 + Worker 异步执行、SSE 实时进度、LangGraph Supervisor + 专业 Agent 编排、Pandas 数据分析、PDF RAG 检索、图片 OCR、Markdown/DOCX/PDF 报告导出和 Docker Compose 生产部署。

适合强调：后端开发、全栈开发、文件处理、数据分析工具。

### 标准版

InsightFlow Agent：基于 FastAPI + React + LangGraph 构建的多模态文档与数据分析 Agent 平台。系统实现多用户认证、工作区数据隔离、五类文件统一理解、文件关系确认、计划确认、数据库任务队列 + 独立 Worker + SSE、Supervisor + 五个专业 Agent、Pandas/Matplotlib/PyMuPDF/Tesseract/RAG 工具链、Markdown/DOCX/PDF 三格式报告、配额/监控/评估/备份系统和 Docker 国内单机生产部署。

适合强调：AI 应用开发、AI Agent 开发、RAG 应用开发。

### 强化版

InsightFlow Agent：独立设计并实现一个面向多用户的多模态文件分析 Agent 平台。从零搭建 FastAPI + React 前后端闭环，涵盖用户认证/工作区隔离/CSRF、五类文件理解与关系确认、数据库持久化任务队列与独立 Worker、SSE 实时进度与协作式取消、LangGraph Supervisor + 五个专业 Agent 架构、工具/Prompt 注册中心、多工作表 Pandas 分析、PDF 分页 RAG 检索与引用、扫描 OCR、三格式报告版本管理与导出、确定性质量审核、配额/监控/评估/备份系统，以及 Docker Compose + Nginx 同域国内单机生产部署包。项目主线代码已封板（`2.0.0-rc.1`），90 后端测试 + 10 前端测试全部通过。

适合强调：AI Agent 工程化、工具调用编排、端到端项目交付能力。

## 面试时 1 分钟介绍话术

InsightFlow Agent 是我做的一个多用户多模态文档与数据分析 Agent 平台，版本号 2.0.0-rc.1。它不是普通聊天机器人，而是面向真实文件的任务执行系统。

用户可以注册账号（需邀请码），创建工作区，上传 CSV、Excel、PDF、图片或 Markdown 文件。系统会自动解析文件、生成 Profile、建议文件角色和文件间关系。用户确认关系后，输入自然语言任务需求。Supervisor 会检查信息完整性，不够就主动追问；信息充分后生成执行计划让用户确认、修改或取消。

用户确认计划后，任务进入数据库队列，独立 Worker 领取执行。五个专业 Agent 各司其职：File Understanding Agent 负责理解文件、Data Analysis Agent 做 Pandas 分析、Document Research Agent 做 PDF/Markdown 检索、Report Agent 生成报告、Quality Review Agent 进行质量审核。前端通过 SSE 实时展示进度，支持断线恢复。

最终生成带引用、图表、异常说明和限制的完整报告，支持 Markdown、DOCX、PDF 导出。整个系统有配额、监控、评估和备份/恢复，并通过 Docker Compose 完成国内单机生产部署包。

代码主线已封板，90 个后端测试、10 个前端测试全部通过，85 条 deterministic 评估全部命中。后续需要用户自行完成服务器购买、域名备案和公网上线。

## 这个项目为什么是 Agent？

它具备任务型 Agent 的核心特征：

- 一个 Supervisor 负责理解用户需求、检查完整性、生成版本化执行计划和调度专业 Agent；
- 五个专业 Agent 各负责一类任务，边界清晰：文件理解、数据分析、文档检索、报告生成、质量审核；
- Agent 之间通过版本化结构化状态（AgentState）传递信息和引用，不是自由文本对话；
- Tool Registry 和 Prompt Registry 集中管理工具调用和 Prompt 版本，Agent 只能调用已注册工具；
- 确定性代码负责权限、安全、解析、数学计算、状态迁移和持久化；DeepSeek 只做语义判断和表达生成；
- 循环和模型调用次数有明确上限，Supervisor 不能无限重新规划，Quality Review 不能无限要求重写；
- OCR、文件解析、图表生成和 DOCX/PDF 导出是确定性工具而非 Agent，Agent 只决定"是否需要、怎么做"。

它不是为了"自由聊天"，而是为了"把分散文件变成可核验报告"。

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
2. 检索时基于关键词/TF-IDF 匹配，返回相关片段及其页码和文件 ID；
3. Document Research Agent 基于检索片段生成事实时，每条事实必须附带 `citation_id`、文件 ID、页码/块 ID；
4. Report Agent 使用引用 ID 生成脚注，确定性代码校验每个引用 ID 是否可解析到真实的 chunk 记录；
5. Quality Review Agent 检查引用覆盖率和引用存在性。

当前 RAG 使用关键词/TF-IDF 检索，不是语义向量检索。引用保证来自确定性校验（引用 ID 可解析性、页码存在性），不是依赖模型承诺。

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

V2 代码主线已封板，以下为当前已知限制：

1. 未购买中国内地服务器/域名/ICP 备案/HTTPS 证书；
2. 未执行公网部署和真实网络测试；
3. 未使用真实 DeepSeek 进行端到端质量评估；
4. deterministic 评估 1.0 是规则自检，不代表真实 DeepSeek 模型准确率；
5. SQLite 单 Worker 只适合约 5 人低并发，不支持多实例；
6. 文件理解仍为同步 HTTP 处理，未迁入任务队列；
7. 未支持任意 Agent 节点暂停/恢复；
8. 不支持强制终止外部 LLM 调用；
9. RAG 使用关键词/TF-IDF 检索，非语义向量检索；
10. 未迁移 PostgreSQL、对象存储、专业队列；
11. 单机部署无高可用/多实例；
12. 未创建 Git Tag 或 GitHub Release；
13. 未建设自动化 E2E 回归测试；
14. 未配置 GitHub Actions CI/CD。

## 代码是否由 AI 辅助？

诚实回答：在开发中使用了 AI 编程助手提高效率。但我负责：

- 需求拆解和阶段划分（V2-01 到 V2-08 的实施顺序和边界）；
- 关键架构决策（Supervisor + 子 Agent 的职责划分、数据库队列 vs Celery 的取舍、取消/重试的语义设计、文件关系的用户确认机制）；
- 每一阶段的验证标准制定和实际测试执行；
- 调试和排错（CORS、CSRF、Tesseract 环境、Docker 构建、Pandas 未来警告、datetime.utcnow 弃用）；
- 文档整理和面试材料撰写。

AI 编程助手是工具，项目架构、取舍、验证和交付由我把控。

## 本人在项目中的真实职责

我负责从需求分析、架构设计、数据库迁移、后端 API、Agent 工作流、RAG、OCR、文件处理、报告系统、前端页面、Docker 部署、运维脚本到文档整理的端到端实现。每个阶段我都限定范围、先验证再推进，并完成了 90 个后端测试、10 个前端测试、85 条 deterministic 评估和完整的部署包交付。

项目的重点是工程闭环：不是单点算法或某个模型的效果，而是从用户注册到最终报告交付的完整系统。

## V2 适合岗位

- AI 应用开发 实习/初级
- AI Agent 开发 实习/初级
- Python 后端开发 实习/初级
- 全栈 AI 应用开发 实习/初级
- RAG 应用开发 实习/初级
