# InsightFlow Agent V2 产品需求与目标架构设计

> 实施状态更新（V2-04）：迁移基线、认证、工作区隔离、统一文件理解、版本化 Profile、文件关系确认和 Workspace Context 已完成；计划草稿/确认、主动追问、数据库队列、独立 Worker、租约、SSE/轮询、取消、局部重试、Supervisor、五个专业 Agent、AgentState、Tool/Prompt Registry、确定性 Quality Review 和 Markdown 报告闭环已经落地。Word/PDF 新导出、任意暂停恢复、PostgreSQL、对象存储和生产部署仍未实现。

> 文档状态：设计稿，不代表已实现
> 编写日期：2026-07-23
> 设计依据：当前真实代码、当前 SQLite 表结构、`docs/PROJECT_AUDIT.md`
> 本阶段边界：只进行产品与技术设计，不修改业务代码、前端代码、数据库、依赖和真实环境配置

## 0. 执行摘要

### 0.1 推荐的 V2 产品定位

InsightFlow Agent V2 定位为：

> **面向学生与求职者的多模态资料分析与完整报告生成 Agent。**

产品不以“自由聊天”作为最终价值，而以“把一组分散资料变成可核验、可修改、可下载的完整分析报告”作为核心闭环。报告是主要交付物，在线回答、图表、引用和 Agent 轨迹都是报告生成过程中的中间产物或证据。

建议首批聚焦两类高价值场景：

1. 学生资料分析：将实验数据、问卷表格、课程要求、论文 PDF、课堂截图和 Markdown 笔记综合为课程分析或研究报告。
2. 求职资料分析：将岗位表格、招聘说明 PDF、岗位截图、个人经历资料和 Markdown 记录综合为岗位对比、能力差距和行动建议报告。

不建议在 V2 必须实现第一批同时扩展成通用办公 Agent、开放式代码执行平台或无限自治的多 Agent 平台。

### 0.2 当前真实基线

本设计不是从空白项目出发。经代码和只读数据库核对，当前版本具备以下基础：

- 后端为 FastAPI + SQLAlchemy + SQLite，前端为 React + Vite。
- 当前实际表只有 `files`、`tasks`、`tool_calls`、`file_chunks`。
- 当前上传支持 CSV、XLSX、PDF、PNG、JPG、JPEG，不支持 Markdown。
- 当前 Excel 只解析第一个工作表；表格分析与图表也只读取第一个工作表。
- 当前 PDF 使用 PyMuPDF 提取文本并以自定义 TF-IDF/关键词方式检索，不是持久化语义向量检索。
- 当前图片 OCR 调用链存在，但依赖外部 Tesseract 和语言包，运行环境效果尚未完整验证。
- 当前 Agent 是固定线性 LangGraph：分类 → 计划 → 路由 → 单工具执行 → 结果整理 → 保存。
- 当前多文件能力依赖关键词命中；多数单文件工具只使用 `file_ids[0]`。
- 当前 `POST /api/tasks` 同步完成整个任务，没有队列、计划确认、追问、取消、局部重试或实时事件流。
- 当前所有 API 无登录、无用户归属、无权限隔离。
- 当前文件 API 会返回服务器本地 `file_path`；图表通过公开静态目录访问。
- 当前报告是 Markdown 文件，不支持 Word、PDF 导出，也没有独立报告版本表。
- 当前前端通过本地状态切换“文件、工作区、历史”三个页面，没有 URL 路由。
- 当前测试主要是健康检查、配置和模块级 smoke test，没有真实文件与端到端回归集。

因此，V2 必须按“先建立身份与数据边界，再升级文件理解和任务执行”的顺序迁移，不能直接在当前全局数据模型上叠加多用户功能。

### 0.3 关键架构决策

| 主题 | 推荐决策 |
| --- | --- |
| 最终成果 | 版本化、可追溯、可下载的完整报告 |
| 多 Agent | 1 个 Supervisor + 5 个边界清晰的专业 Agent；解析、OCR、图表、导出仍是工具 |
| 模型职责 | DeepSeek 负责语义判断、追问、计划、综合表达和语义审核；确定性代码负责权限、状态、数值、解析、执行和持久化 |
| 计划确认 | 计划草稿必须由用户确认、修改或取消后才能进入队列 |
| 执行方式 | 持久化任务队列 + 独立 worker；低并发阶段先使用单 worker 和数据库租约，不要求第一批引入复杂分布式队列 |
| 实时进度 | SSE 为主、短轮询为降级；暂不使用 WebSocket |
| 取消 | 取消标记 + worker 协作式检查 + 步骤边界终止；不能承诺瞬时中断所有外部调用 |
| 重试 | 按 `task_step` 局部重试，最大次数受限；支持从已确认计划创建新的执行版本 |
| 认证 | 服务端不透明 Session Cookie，登录不需要邀请码，注册必须校验邀请码 |
| 数据隔离 | 所有工作区、文件、任务、报告查询必须同时做当前用户归属校验 |
| 本地数据库 | 开发和首个低并发单机版可继续 SQLite；禁止在多实例下共享 SQLite 文件 |
| 文件存储 | 通过存储适配层隔离本地文件与对象存储，API 只返回资源 ID 和受控下载地址 |
| 数据库迁移 | 引入 Alembic；不再把 `Base.metadata.create_all()` 当作生产迁移机制 |
| 部署 | 5 人以内可先单机部署前端静态文件、API、worker、SQLite 和持久卷；保留切换数据库和对象存储的接口 |

## 1. 产品定位、目标与非目标

### 1.1 产品目标

V2 的核心目标是让用户在一个长期保存的工作区内完成：

```text
注册/登录
  → 创建工作区
  → 上传并自动理解多种资料
  → 确认文件角色与关系
  → 提交自然语言需求
  → 补充必要信息
  → 确认执行计划
  → 查看实时执行
  → 获取完整报告
  → 导出 Word/PDF
  → 在历史工作区继续查看或重新执行
```

### 1.2 产品成功标准

V2 必须实现第一批完成不能只以“接口存在”判断，至少应满足：

1. 用户 A 无法通过 ID 枚举访问用户 B 的任何工作区、文件、任务、事件、报告和下载资源。
2. 五类文件都能进入统一处理状态机，并产生可解释的解析状态。
3. 文件关系只作为候选展示，用户可确认、拒绝和修改。
4. 任务不会在创建请求中同步跑完；用户确认计划后才进入后台执行。
5. 取消、步骤失败、局部重试和从计划重新执行都有明确状态与审计记录。
6. 报告中的数字可追溯到工具结果，文档事实可追溯到文件、页码或章节。
7. Word 和 PDF 导出内容与报告版本一致，下载接口不暴露服务器路径。
8. 有覆盖关键样例的自动评估与回归门禁。

### 1.3 明确非目标

V2 正式版暂缓实现：

- 任意 Agent 节点暂停后从进程内存原地恢复。
- 电子邮件或短信密码重置。
- 子 Agent 之间无限自由对话。
- 高自主、无限循环、自我扩权的多 Agent。
- 直接执行用户输入或模型生成的任意 Python 代码。
- 企业级组织、复杂 RBAC、共享工作区和多人实时协作。
- 多地域、多活或大规模分布式调度。

第一版只承诺任务取消、失败后的受限局部重试，以及基于已有计划创建新的执行。

## 2. 用户画像与核心场景

### 2.1 学生

典型资料：

- 实验或问卷 Excel/CSV；
- 课程要求、论文、研究资料 PDF；
- 扫描件、课堂截图、图表图片；
- Markdown 笔记和报告草稿。

主要任务：

- 对实验或问卷数据做质量检查、统计和可视化；
- 对照课程要求或论文规则检查数据与报告；
- 将图片中的文字或表格线索与其他材料综合；
- 输出带引用、风险、限制和行动建议的课程/研究报告。

### 2.2 求职者

典型资料：

- 岗位清单、投递记录、技能矩阵 Excel/CSV；
- 招聘说明、公司资料、个人简历 PDF；
- 岗位截图、面试题截图；
- Markdown 求职记录、项目经历和准备清单。

主要任务：

- 对比多个岗位和技能要求；
- 从岗位说明和个人资料中识别差距；
- 将截图信息纳入岗位对比；
- 输出岗位优先级、风险和下一步行动报告。

### 2.3 产品设计原则

1. **先证据，后结论**：数字来自确定性分析，事实来自可定位引用。
2. **自动推断可修正**：文件角色和关系必须标明置信度与证据，不能伪装成事实。
3. **高影响操作需确认**：正式执行前确认计划；重置密码、删除数据等操作需审计。
4. **过程可解释**：展示阶段、步骤、工具、耗时、错误和降级，不展示内部思维链。
5. **失败可定位**：区分文件、步骤、工具和模型调用层面的失败。
6. **成本有上限**：每个任务有模型调用、重试、文件数、页数和执行时间预算。

## 3. 功能范围与优先级

### 3.1 V2 必须实现第一批：形成可用闭环

| 能力组 | 第一批范围 |
| --- | --- |
| 身份与隔离 | 注册、登录、邀请码、Session、普通用户/管理员、密码重置申请、临时密码、工作区级归属校验 |
| 工作区 | 创建、查看、改名、归档、历史工作区 |
| 文件 | Excel、CSV、PDF、图片、Markdown；多文件上传；自动解析、摘要、结构、角色、标签 |
| 文件关系 | 自动候选、证据、置信度、确认、拒绝、编辑 |
| 任务 | 追问、计划草稿、修改/确认/取消、后台队列、SSE 进度、取消、局部重试、从计划重跑 |
| Agent | Supervisor、File Understanding、Data Analysis、Document Research、Report、Quality Review |
| 报告 | 完整结构化报告、图表、引用、异常、建议、限制；Word/PDF 导出 |
| 历史 | 工作区内查看文件、任务、执行事件、报告版本 |
| 管理 | 邀请码、用户基本状态、密码重置申请、临时密码 |
| 质量 | 基准样例、自动指标、端到端回归、模型调用与工具调用记录 |

### 3.2 V2 必须实现第二批：质量与运营增强

本节全部能力都是 V2 正式版本的必做项，不再视为可选增强；允许在第一批闭环稳定后分阶段实施。

- 报告模板选择。
- 点赞、纠错、基于同一计划重新生成。
- Prompt 版本记录和回归绑定。
- 模型输入输出摘要、工具调用、耗时、错误、Token/成本记录。
- 用户级文件大小、数量、存储量和任务频率限制。
- 管理员查看用户、任务和资源使用的基本状态。
- 模型失败的规则模板或简化报告降级。
- 用户在上传或任务前手动指定每个文件用途。

其中“用户手动指定用途”与第一批的角色修正能力有重叠。建议第一批支持修改系统识别的角色，第二批再增加上传前批量指定和角色模板。

### 3.3 V2 正式版后续增强

- 对象存储、PostgreSQL 和更专业的队列后端切换。
- 语义 embedding 和持久化向量检索。
- 更丰富的报告模板、团队共享和组织权限。
- 更完整的运营监控和自动数据保留策略。
- 在评估证明有收益后，再考虑增加专业 Agent 或 MCP 化工具。

## 4. 用户完整流程

### 4.1 注册与登录

1. 新用户打开注册页，输入账号、密码、确认密码和邀请码。
2. 系统校验账号格式、密码强度、邀请码状态/有效期/使用次数。
3. 创建用户后消耗一次邀请码额度，建立 Session。
4. 已注册用户登录只输入账号和密码，不需要邀请码。
5. 忘记密码时提交重置申请；页面始终返回相同提示，避免暴露账号是否存在。
6. 管理员在后台查看申请并设置一次性临时密码；数据库只保存新密码哈希，不长期保存临时密码明文。
7. 用户使用临时密码登录后，系统根据 `must_change_password` 强制进入修改密码流程。
8. 用户成功修改密码后，请求状态变为 `completed`，原有登录会话失效。

### 4.2 工作区与资料

1. 用户创建工作区，填写名称和可选目标说明。
2. 用户批量上传文件。
3. 系统先做格式、大小、文件头、哈希和安全校验，再保存资源。
4. 后台统一处理文件，页面展示每个文件的解析阶段和错误。
5. 系统生成结构摘要、内容摘要、角色候选、标签和关系候选。
6. 用户确认、拒绝或修改角色与关系；低置信度关系默认不参与自动分析。

### 4.3 任务与计划

1. 用户选择工作区文件并输入分析需求。
2. Supervisor 先检查目标、范围、输出形式和文件是否足够。
3. 信息不足时进入 `awaiting_clarification`，最多进行受限轮次追问。
4. 信息充分后生成版本化计划草稿。
5. 用户可修改允许编辑的步骤参数、文件选择和输出要求，或确认/取消。
6. 确认后任务进入队列，worker 按计划执行。
7. 页面通过 SSE 显示阶段、百分比、当前步骤、工具、错误与降级。
8. Quality Review 检查证据、数字、结构和风险；只允许受限重试。
9. 通过后生成报告版本，并按需导出 Word/PDF。

### 4.4 历史与重新执行

- 用户可在历史工作区查看文件理解结果、关系确认记录、任务、计划版本、执行版本、事件和报告版本。
- “重新执行”不覆盖旧任务和旧报告，而是基于已确认计划创建新的 `agent_run` 或新任务执行版本。
- 修改原文件、文件关系或计划后，应明确提示旧报告基于旧快照，不能无提示复用。

## 5. 目标总体架构

```text
React Web
  ├─ 认证与工作区页面
  ├─ 文件理解/关系确认
  ├─ 计划确认
  ├─ SSE 执行进度
  └─ 报告预览与导出
          │
          ▼
FastAPI API
  ├─ Auth/Permission
  ├─ Workspace/File/Relation API
  ├─ Task/Plan/Progress API
  ├─ Report/Export API
  └─ Admin/Evaluation API
          │
          ├──────────────┐
          ▼              ▼
Relational DB        Storage Adapter
SQLite/PostgreSQL    Local/Object Storage
          │
          ▼
Durable Task Queue / Lease
          │
          ▼
Worker + LangGraph
  └─ Supervisor
      ├─ File Understanding Agent
      ├─ Data Analysis Agent
      ├─ Document Research Agent
      ├─ Report Agent
      └─ Quality Review Agent
          │
          ├─ Deterministic Tools
          └─ DeepSeek Gateway
```

架构原则：

- API 进程不执行长任务，只创建记录、校验权限、变更状态和提供查询/事件。
- worker 可与 API 部署在同一台机器，但必须是逻辑独立的执行单元。
- 文件内容通过存储适配层访问，业务代码不依赖某个云存储 SDK 的 URL 格式。
- DeepSeek 通过统一模型网关调用，Prompt、超时、预算、重试和日志在网关层统一管理。
- 大文本、原文件和导出文件不直接塞入任务状态或数据库 JSON；状态中保存资源引用。

## 6. Supervisor 与专业 Agent 设计

### 6.1 Supervisor Agent

**输入**

- 当前用户和工作区 ID；
- 用户需求、已完成追问答案；
- 选中文件的结构摘要、角色、标签、已确认关系；
- 可用工具清单及约束；
- 当前计划版本、步骤结果引用、预算与取消状态。

**输出**

- `completeness_check`：是否需要追问、缺失项和追问问题；
- `task_intent`：任务类型、目标、输出要求、风险等级；
- `task_plan`：有序步骤、依赖、Agent、工具、输入引用、验收条件；
- `dispatch_decision`：下一专业 Agent/步骤；
- `execution_summary`：完成、失败、降级或需要用户处理。

**可用工具**

- 读取工作区已授权的文件摘要、关系和计划；
- 创建计划草稿、任务步骤和事件；
- 查询步骤结果；
- 派发预定义专业 Agent；
- 检查预算、取消标记和重试次数。

**不应承担**

- 不直接解析文件、运行 OCR、执行 Pandas 分析或生成图表。
- 不直接读服务器路径。
- 不绕过用户确认执行计划。
- 不动态创建新工具或执行模型生成代码。
- 不在失败后无限重新规划。

### 6.2 File Understanding Agent

**输入**

- 文件元数据和确定性解析结果；
- 工作区目标；
- 已有角色、标签、关系候选和用户修正。

**输出**

- 受 schema 约束的内容摘要；
- 文件角色候选、标签、用途建议；
- 文件关系候选、置信度、证据和需要用户确认的原因；
- 对无法理解或疑似冲突内容的警告。

**可用工具**

- 文件元数据读取；
- Excel/CSV 结构读取；
- PDF/Markdown 分块检索；
- OCR 文本读取；
- 字段相似度、哈希、时间范围和关键词重叠计算。

**不应承担**

- 不直接修改用户确认过的角色或关系。
- 不把候选关系写成确定事实。
- 不完成正式数据分析、报告写作或权限判断。
- 不自行执行 OCR/解析实现；只能调用工具并读取结果。

### 6.3 Data Analysis Agent

**输入**

- 用户分析目标；
- 经过确认的表格文件、工作表、列结构和文件关系；
- 允许的分析工具与参数范围；
- 上游质量警告。

**输出**

- 结构化统计结果；
- 数据质量问题、异常、可复现的计算说明；
- 图表规格和图表资产引用；
- 每个结论所用文件、工作表、字段和过滤条件；
- 无法完成的分析及原因。

**可用工具**

- 安全表格读取；
- schema/profile；
- 缺失值、重复值、分布、分组、连接、对比、趋势、异常检测等预设 Pandas 工具；
- 预设图表生成器；
- 数字一致性校验器。

**不应承担**

- 不执行任意 Python、SQL、Shell 或用户表达式。
- 不凭模型心算生成最终数字。
- 不解释 PDF 规则或写最终报告。
- 不自行决定跨表连接键；低置信度连接必须依赖已确认关系或用户确认。

### 6.4 Document Research Agent

**输入**

- 用户问题或计划中的研究子任务；
- PDF、Markdown、OCR 文本块；
- 文件范围、已确认关系和检索限制。

**输出**

- 事实列表；
- 每条事实对应的 `citation_id`、文件 ID、页码/章节/文本块；
- 支持证据、反向证据、冲突和信息缺口；
- 依据不足时的明确拒答。

**可用工具**

- PDF/Markdown/OCR 分块检索；
- 关键词/语义检索适配器；
- 章节和页码定位；
- 引用去重、片段扩展和冲突检测。

**不应承担**

- 不把检索相似度当作事实正确性。
- 不伪造页码、章节或引用。
- 不替代 Data Analysis Agent 计算表格数字。
- 不直接生成最终 Word/PDF。

### 6.5 Report Agent

**输入**

- 已确认计划；
- 数据分析结果、图表资产、文档事实与引用；
- 文件/任务概述；
- 已知异常、限制和质量审核反馈；
- 报告模板和语言要求。

**输出**

- 结构化 `report_document`，而不是只有一段 Markdown；
- 报告章节、表格、图表引用、引用脚注、结论、建议、限制；
- 可供确定性渲染器生成 HTML/Markdown/DOCX/PDF 的统一中间结构。

**可用工具**

- 报告 schema 校验；
- 引用解析；
- 图表/资产读取；
- 报告模板；
- DOCX/PDF 渲染工具。

**不应承担**

- 不重新计算数字。
- 不添加不存在的引用或图表。
- 不直接修改上游分析结果。
- 不把导出渲染失败解释为分析成功。

### 6.6 Quality Review Agent

**输入**

- 计划验收条件；
- 所有步骤结果；
- 报告结构；
- 数字来源、引用映射、错误和降级记录；
- 剩余重试预算。

**输出**

- `pass`、`pass_with_warnings`、`revise`、`failed` 或 `needs_user`；
- 问题类别、严重度、证据；
- 可重试的目标步骤和修正指令；
- 不可自动修复的问题及报告警告。

**可用工具**

- 报告字段完整性检查；
- 数字重算/交叉校验；
- 引用存在性和引用覆盖检查；
- 资产存在性检查；
- 计划步骤完成性检查；
- DeepSeek 语义一致性审查。

**不应承担**

- 不直接改写上游事实以“让报告通过”。
- 不无限要求 Report Agent 重写。
- 不重试权限、取消、配额、损坏文件等非瞬时错误。
- 不以语言风格问题阻止一份事实正确的报告交付。

### 6.7 Agent 间结构化状态

Agent 之间只传递版本化结构和资源引用，建议核心状态如下：

```json
{
  "schema_version": "2.0",
  "task_id": 123,
  "workspace_id": 10,
  "user_id": 7,
  "request": {
    "original_text": "……",
    "clarifications": [],
    "output_requirements": {}
  },
  "input_snapshot": {
    "file_versions": [],
    "confirmed_relation_ids": []
  },
  "plan": {
    "plan_id": 15,
    "version": 2,
    "confirmed_at": "……"
  },
  "execution": {
    "run_id": 31,
    "current_step_id": 205,
    "step_result_refs": [],
    "artifact_refs": [],
    "citation_refs": [],
    "errors": []
  },
  "controls": {
    "cancel_requested": false,
    "max_model_calls": 12,
    "used_model_calls": 4,
    "max_step_retries": 1,
    "deadline_at": "……"
  }
}
```

约束：

- 所有结构都必须通过 Pydantic/schema 校验。
- 状态中不放 API Key、密码、Session、服务器绝对路径和完整大文件文本。
- 每个步骤输入引用固定的文件版本和关系版本，保证重试可复现。
- Agent 输出不能直接变更任务状态；状态迁移由确定性编排器完成。

### 6.8 确定性代码与 DeepSeek 的职责

| 必须由确定性代码完成 | 适合使用 DeepSeek |
| --- | --- |
| 注册、登录、密码哈希、Session、权限校验 | 需求完整性判断和追问措辞 |
| 文件类型/大小/哈希/存储与状态迁移 | 内容摘要、角色和关系语义候选 |
| Excel/CSV/PDF/Markdown 解析与 OCR 调用 | 任务意图和计划草稿 |
| 数据统计、连接、排序、异常计算 | 基于工具结果解释趋势和风险 |
| 图表数据准备与图像生成 | 跨文档事实综合与冲突摘要 |
| 队列、取消、超时、重试、幂等 | 报告叙事、行动建议和限制表述 |
| 引用 ID、页码/章节映射 | 语义层面的引用充分性审查 |
| 报告 schema 校验和 DOCX/PDF 渲染 | 在严格证据范围内进行质量审阅 |
| 配额、日志脱敏、数据删除 | 不确定性说明的自然语言表达 |

DeepSeek 不负责权限、数值真值、文件路径、状态写入、工具执行权限和循环终止判断。

### 6.9 循环和调用上限

建议第一批默认上限，最终值需通过评估调整：

- 追问最多 2 轮，每轮最多 3 个问题。
- Supervisor 计划生成最多 2 次：初稿一次、用户修改后重整一次。
- 每个专业 Agent 每个步骤默认 1 次模型调用，语义修订最多 1 次。
- 单步骤自动重试最多 1 次；单任务自动重试步骤总数最多 2 个。
- Quality Review 最多 2 轮，第二轮后仍不通过则 `failed`，或将任务标记为 `completed` 并单独记录质量警告，不再循环。
- 标准任务模型调用总上限建议 12 次；超过前必须停止并给出降级结果或明确失败。
- 每个外部模型调用设置连接超时、读取超时和最大输出 Token。
- 所有预算写入执行快照，管理员账号可豁免普通使用配额，但不能绕过系统级安全上限。

### 6.10 Quality Review 触发重试的条件

允许触发局部重试：

- 报告缺少计划明确要求的章节或资产，但上游数据存在。
- 数字与工具结果不一致。
- 引用 ID 无法解析、引用与陈述明显不匹配或回答未覆盖关键证据。
- 某个可重试工具发生超时、临时外部错误或生成了 schema 不合法的输出。
- 报告中出现未在上游证据中找到的高风险事实。

不自动重试：

- 用户取消。
- 权限失败、配额不足、文件损坏或格式不支持。
- 需要用户确认连接键、角色、关系或业务定义。
- 同一步骤已经达到重试上限。
- 只有措辞风格差异，不影响事实与结构。

重试必须指向具体 `task_step`，并记录 `retry_of_step_id`、原因和新 attempt；不能把整个任务无差别重跑。

### 6.11 OCR、解析、图表为什么是工具

OCR、文件解析、图表生成有明确输入、确定性接口和可校验输出，没有独立目标、长期上下文或决策收益。把它们包装成 Agent 会额外引入 Prompt、状态同步、重试和模型成本，却不能提高结果质量。

因此：

- Agent 决定“是否需要 OCR、解析哪份文件、生成什么图表”。
- 工具负责“按受控参数执行 OCR、解析或绘图并返回结构化结果”。
- 编排器负责权限、超时、幂等、状态和错误。

## 7. 文件理解与关系识别

### 7.1 统一处理流程

```text
接收上传
  → 校验账号/工作区/配额
  → 校验扩展名、文件头、MIME、大小
  → 计算 SHA-256 并保存
  → 创建 files/workspace_files
  → 排队解析
  → 类型专用确定性解析
  → 生成标准化结构与文本块
  → DeepSeek 生成摘要/角色/标签候选
  → 规则 + 模型生成关系候选
  → 用户确认/拒绝/编辑
  → 文件状态 ready
```

上传成功只表示文件已安全保存，不等于已经解析或理解。

### 7.2 文件元数据

建议统一保存：

- 资源标识：`id`、`owner_user_id`、`storage_backend`、`object_key`。
- 原始信息：`original_filename`、`extension`、`detected_mime_type`、`size_bytes`、`sha256`。
- 文件版本：`version`、`replaces_file_id`、`uploaded_at`。
- 安全信息：文件头校验结果、扫描状态、拒绝原因。
- 处理信息：`parse_status`、`understanding_status`、`parse_error_code`、`parse_error_message`、开始/完成时间、解析器版本。
- 内容信息：`summary`、`language`、`page_count`/`sheet_count`、结构摘要引用。
- 不对前端返回：绝对 `file_path`、对象存储内部密钥、临时目录和异常堆栈。

建议解析状态独立于文件生命周期：

```text
uploaded → queued → parsing → parsed → understanding → ready
                         └──────────────→ failed
```

重试时增加处理 attempt，不覆盖旧错误记录。

### 7.3 各类型解析结果

#### Excel

- 所有工作表名称、可见性、行数、列数。
- 每个工作表的列名、推断数据类型、缺失数、唯一值数、样本值。
- 日期、数值、文本、布尔、ID 候选列。
- 合并单元格、空工作表、重复列名和公式存在性警告。
- 只保留受限数量的脱敏样本，不把整表写入 JSON。
- 第一批不执行宏，不计算不可信外部链接。

#### CSV

- 编码、分隔符、表头、行列数、字段类型和样本。
- 解析警告：列数不一致、编码替换、异常大字段、重复表头。
- 与 Excel 使用同一标准化 `table_profile`。

#### PDF

- 页数、文档元数据、书签/目录。
- 每页文本块、页码、块序号、字符范围和文本哈希。
- 章节结构：优先使用书签，其次用标题规则/模型生成候选。
- 文本覆盖率和扫描页比例；文本过少的页面标记为 OCR 候选。
- 引用必须保留文件 ID、页码、块 ID，不只保存摘要。

#### 图片（PNG/JPG/JPEG）

- 宽高、颜色模式、文件大小和 EXIF 安全处理结果。
- OCR 状态、语言、文本、文本块位置和置信度。
- OCR 失败或低置信度时保留警告。
- 第一批以 OCR 文本为主，不把“通用视觉理解”假装成已实现能力。

#### Markdown

- 编码、标题层级、段落、列表、表格、代码块、链接和图片引用。
- 每个文本块保留标题路径、块序号和字符范围。
- 外部链接只作为文本元数据，不在解析阶段自动访问。
- 代码块只做文本处理，不执行。

### 7.4 文件角色与标签

角色用于说明文件在当前工作区中的用途，而不是文件类型。建议内置角色：

- `primary_data`：主要数据；
- `supplementary_data`：补充数据；
- `rule_or_requirement`：规则/要求；
- `reference_material`：参考资料；
- `evidence`：证据或截图；
- `personal_profile`：个人资料；
- `job_description`：岗位说明；
- `draft`：草稿；
- `unknown`：无法判断。

角色属于 `workspace_files`，同一文件进入不同工作区时可以有不同角色。保存：

- `role`；
- `role_source`：`system`、`user`；
- `role_confidence`；
- `role_reason`；
- `user_confirmed_at`。

标签为多值、低约束信息，如“问卷”“2025 秋季”“产品岗位”“课程要求”。系统标签和用户标签要区分来源。

### 7.5 文件关系候选

建议关系类型：

- `same_schema_append`：结构相同，可纵向合并；
- `joinable_by_key`：可按候选键连接；
- `time_series_parts`：同一数据的不同时段；
- `compare_peer`：同类对象对比；
- `governed_by`：数据受规则/要求约束；
- `supports`：某文件为另一文件提供证据；
- `derived_from`：派生关系；
- `duplicate_or_version`：重复或不同版本；
- `conflicts_with`：内容冲突；
- `unrelated`：无明显关系。

每个候选至少包含：

- `source_file_id`、`target_file_id`、`relation_type`；
- `confidence`，范围 0～1；
- `evidence_json`：相同列名、候选键、日期重叠、标题/关键词、引用等；
- `inference_method`：规则、模型或混合；
- `status`：`pending`、`confirmed`、`rejected`、`edited`；
- `created_by`、`confirmed_by`、时间和版本。

推荐阈值只是 UI 策略，不是真实概率：

- `>= 0.85`：高置信候选，仍需展示确认；
- `0.60～0.84`：普通候选，默认不自动用于连接；
- `< 0.60`：仅在“更多候选”中展示或不保存。

涉及连接键、覆盖更新、规则约束的关系，即使高置信也必须由用户确认后才能进入正式计划。

### 7.6 三类关系示例

#### 示例一：多个 Excel 合并、对比、汇总

文件：

- `岗位_北京.xlsx`：字段为岗位、公司、薪资、技能、日期；
- `岗位_上海.xlsx`：字段基本相同；
- `投递记录.xlsx`：字段为岗位、公司、投递状态、投递日期。

候选：

- 北京与上海文件：`same_schema_append`，证据是字段高度重合，置信度 0.94。
- 合并后的岗位表与投递记录：`joinable_by_key`，候选键为“岗位 + 公司”，置信度 0.76。

用户操作：

- 确认前两个表可纵向合并；
- 将连接键修改为“岗位 + 公司 + 城市”，或拒绝直接连接。

执行：

- 确定性工具合并、去重和汇总；
- 报告明确列出合并规则、未匹配记录和数据质量风险。

#### 示例二：Excel 数据与 PDF 规则交叉分析

文件：

- `实验结果.xlsx`；
- `课程评分标准.pdf`。

候选：

- `实验结果.xlsx governed_by 课程评分标准.pdf`，证据是文件名、工作区目标和 PDF 中的指标名称与表格列名重合，置信度 0.82。

用户确认后：

- Document Research Agent 提取评分规则并生成页码引用；
- Data Analysis Agent 根据确定性规则计算达标情况；
- 报告把“计算结果”和“规则引用”分开呈现。

#### 示例三：图片 OCR 与 PDF、Excel 综合分析

文件：

- `岗位截图.jpg`；
- `岗位说明.pdf`；
- `技能矩阵.xlsx`。

候选：

- 图片 `supports` PDF 中的岗位信息，置信度 0.70；
- PDF `compare_peer` Excel 中的技能项目，置信度 0.78。

用户确认后：

- OCR 工具提取截图文本并标记低置信字符；
- Document Research Agent 对齐截图与 PDF 的岗位要求；
- Data Analysis Agent 对比 Excel 技能评分；
- 报告分别标注 OCR 不确定性、PDF 页码引用和表格字段来源。

## 8. 计划确认、执行方式与任务状态机

### 8.1 计划确认流程

```text
draft
  → 完整性检查
  → awaiting_clarification（如需要）
  → planning
  → awaiting_confirmation
      ├─ 用户修改 → planning（生成新计划版本）
      ├─ 用户取消 → cancelled
      └─ 用户确认 → queued
  → running
  → reviewing
      ├─ 通过 → completed
      ├─ 可修复 → retrying → running/reviewing
      └─ 不可修复 → failed
```

计划草稿应包含：

- 任务目标与输出形式；
- 使用的文件和已确认关系；
- 每一步的 Agent、工具、输入、依赖；
- 预期产物与验收条件；
- 可能的限制、预计模型调用上限；
- 哪些步骤会生成图表、引用和报告。

用户可修改的内容建议限制为文件选择、关系选择、分析范围、分组字段、输出重点、报告模板和步骤启用状态。用户不能通过修改计划加入任意代码、未知工具或越权文件。

### 8.2 状态定义

| 状态 | 含义 | 可进入状态 |
| --- | --- | --- |
| `draft` | 任务已创建，尚未完成完整性检查 | `awaiting_clarification`、`planning`、`cancelled` |
| `awaiting_clarification` | 等待用户补充信息 | `planning`、`cancelled` |
| `planning` | 正在生成或修订计划草稿 | `awaiting_confirmation`、`failed`、`cancelled` |
| `awaiting_confirmation` | 等待用户确认、修改或取消计划 | `planning`、`queued`、`cancelled` |
| `queued` | 已确认，等待 worker 领取 | `running`、`cancelled`、`failed` |
| `running` | 正在执行计划步骤 | `reviewing`、`retrying`、`failed`、`cancelled` |
| `reviewing` | 正在执行质量审核 | `completed`、`retrying`、`failed`、`cancelled` |
| `retrying` | 已创建重试 attempt，等待或正在重试 | `queued`、`running`、`reviewing`、`failed`、`cancelled` |
| `completed` | 报告已生成并通过交付门槛 | 终态；重新执行创建新 run |
| `failed` | 达到上限或发生不可恢复失败 | 可由用户发起新的重试/run |
| `cancelled` | 用户或系统取消 | 终态；重新执行创建新 run |

所有状态迁移由一个确定性状态机服务校验，禁止路由函数或 Agent 随意写字符串。

### 8.3 当前同步 HTTP 方式的问题

当前 `POST /api/tasks` 在请求内完成 LangGraph、文件读取、OCR、RAG、图表、LLM 和报告，存在：

- 反向代理或浏览器超时导致用户看见失败，但后台可能仍在执行。
- API worker 被长任务占满，其他登录、列表和下载请求受影响。
- 无法可靠展示中间进度或取消。
- 进程重启后没有任务领取、租约和恢复语义。
- 重试只能整段重跑，容易重复生成图表、报告和模型费用。
- HTTP 响应与数据库提交之间可能出现不一致。

### 8.4 V2 任务队列

V2 必须实现第一批需要持久化任务队列，但在 5 人以内不必一开始引入复杂分布式系统。

建议：

- 使用数据库中的任务/步骤状态、`available_at`、`lease_owner`、`lease_expires_at` 实现低并发持久化领取。
- 独立 worker 进程轮询并领取任务；初期并发设为 1。
- 每个步骤使用幂等键，产物写入后再原子更新步骤状态。
- worker 崩溃后，超过租约的步骤可由同一 worker 重新领取。
- 当迁移到多实例或更高并发时，再替换为专业队列后端；业务层只依赖队列接口。

不建议把 FastAPI `BackgroundTasks` 作为可靠队列，因为进程重启后任务会丢失，也缺少租约和重试语义。

### 8.5 实时进度：SSE 优先

推荐 SSE：

- 当前场景主要是服务器向浏览器单向推送。
- 浏览器原生支持断线重连和 `Last-Event-ID`。
- 比 WebSocket 更容易经过普通反向代理，也更符合低并发预算。
- 事件同时持久化，断线后可按游标补拉。

事件示例：

- `task.status_changed`；
- `plan.created`；
- `step.started`、`step.progress`、`step.completed`、`step.failed`；
- `tool.started`、`tool.completed`；
- `review.completed`；
- `report.ready`；
- `task.cancelled`。

SSE 不可用时，前端降级到 2～5 秒的增量轮询。WebSocket 暂不引入，除非后续出现高频双向协作需求。

### 8.6 取消任务

1. 用户调用取消接口，API 做归属校验。
2. 数据库写入 `cancel_requested_at`、`cancel_requested_by`，并追加事件。
3. `draft`、等待追问、等待确认、排队中的任务可立即转为 `cancelled`。
4. `running`/`reviewing` 中的 worker 在步骤开始前、工具调用前后、文件循环和模型调用后检查标记。
5. 已经发出的外部 HTTP 调用只能依靠请求超时或客户端支持的取消，不能承诺瞬时停止。
6. 已完成的原子产物保留为审计记录，但不被标记为最终报告；临时文件由清理任务处理。

### 8.7 局部重试和重新执行

局部重试：

- 以失败 `task_step` 为单位创建新 attempt。
- 复用未失效的上游结果。
- 当前步骤及依赖其输出的下游步骤标记为待重新计算。
- 工具必须使用幂等键，避免重复资产。

从计划重新执行：

- 固定原计划版本和输入文件快照，创建新的 `agent_run`。
- 旧执行和旧报告保留。
- 如果文件版本、关系或 Prompt 已变化，页面明确提示“复现实验”与“使用最新配置重新运行”的区别。

### 8.8 必须持久化的中间结果

- 文件解析 profile、文本块、OCR 结果和解析器版本。
- 文件角色、关系候选、用户确认记录。
- 追问问题和用户答案。
- 每个计划版本和确认记录。
- task step、attempt、输入引用、输出引用、错误和耗时。
- Agent run、模型名称、Prompt 版本、调用结果摘要、Token 和错误。
- 工具调用、图表和其他资产。
- 文档事实、引用、数字来源。
- Quality Review 结果和重试指令。
- 报告版本、导出文件、事件流和用户反馈。

### 8.9 暂不做任意暂停恢复

任意节点原地恢复要求序列化模型上下文、进程内对象、文件句柄、外部调用状态和非幂等工具副作用，复杂度远高于当前规模。第一批通过“小步骤、持久化结果、幂等执行、步骤边界重试”获得大部分可靠性收益，无需承诺进程指令级恢复。

## 9. 登录、权限和管理端

### 9.1 页面逻辑

- 登录页：账号、密码、登录；提供“注册”和“申请重置密码”链接。
- 注册页：账号、密码、确认密码、邀请码。
- 密码重置申请页：账号和可选说明；提交结果不暴露账号是否存在。
- 邀请码不出现在登录必填项中。

### 9.2 Session 机制

推荐服务端不透明 Session：

- 登录成功生成高熵随机 token。
- 数据库只保存 token 哈希、用户 ID、过期时间、最后使用时间和撤销时间。
- 浏览器通过 `HttpOnly`、`Secure`、`SameSite=Lax` Cookie 携带。
- 不把认证 token 放入 `localStorage`。
- 修改密码、管理员重置、账号停用时撤销所有 Session。
- 生产环境尽量同域部署；跨域时必须补充严格 CORS、CSRF 和 Cookie 策略。

与 JWT 相比，服务端 Session 更适合当前小规模产品：易撤销、易停用、实现边界清晰。若后续开放第三方 API，再设计短期访问 Token。

### 9.3 密码与角色

- 密码使用成熟的 Argon2id 或 bcrypt 实现，不自行发明哈希；具体依赖在实施阶段确认。
- 保存 `password_hash`，绝不保存明文或可逆密码。
- 角色先保持 `user`、`admin` 两种。
- 管理员必须正常登录、经过 Session 校验和操作审计。
- 管理员不受普通用户使用配额限制，但仍受文件类型、安全扫描、全局模型预算和并发保护。

### 9.4 邀请码

邀请字段：

- 展示标签、邀请码哈希、状态、有效期、最大使用次数、已使用次数、创建人和更新时间。

安全策略：

- 数据库不保存可直接使用的邀请码明文。
- 创建时只展示一次原始码。
- “修改邀请码”实现为轮换：停用旧码并生成新码；标签、有效期和次数可直接编辑。
- 注册使用邀请码时在同一事务中校验并增加使用次数，防止并发超用。

### 9.5 密码重置

1. 用户提交申请，系统返回统一响应。
2. 管理员查看待处理申请及账号基本信息，不查看旧密码。
3. 管理员批准后生成临时密码，只在当前操作结果中展示一次。
4. 数据库保存新密码哈希，设置 `must_change_password=true`、临时密码过期时间，并撤销旧 Session。
5. 用户用临时密码登录后只能进入修改密码流程。
6. 系统强制用户修改密码；修改成功后将请求状态改为 `completed`，并撤销该用户原有登录会话。
7. 临时密码由管理员通过产品负责人认可的线下渠道交付；系统第一批不发送邮件或短信，也不在列表中再次展示。
8. 所有操作写入审计日志。

### 9.6 数据隔离与接口权限

所有资源查询必须采用“资源 ID + 当前用户归属”：

```text
workspace.id = :workspace_id
AND workspace.owner_user_id = current_user.id
```

文件、任务、报告不能只通过全局 ID 查询后返回。下载、SSE、重试和取消同样必须复用权限依赖。

建议依赖层：

- `get_current_user`；
- `require_active_user`；
- `require_admin`；
- `get_owned_workspace`；
- `get_workspace_file`；
- `get_workspace_task`；
- `get_workspace_report`。

管理员第一批默认只查看账号、任务状态和资源用量元数据，不默认打开普通用户文件内容。若未来需要客服排障，应设计显式授权和审计，而不是隐式越权。

### 9.7 限流与配额

至少需要：

- 登录：按 IP + 账号限速，连续失败增加退避；响应不区分账号不存在或密码错误。
- 注册和重置申请：按 IP 和账号限速。
- 上传：单文件大小、单次文件数、单用户存储量、文件页数/像素上限。
- 任务：并发任务数、每日任务数、模型调用次数、最大 Token、最大运行时间。
- 导出和下载：频率限制，避免重复渲染和带宽滥用。

管理员免普通配额，不免安全上限和审计。

### 9.8 管理员后台最小范围

- 登录后的管理员首页。
- 邀请码列表、创建、编辑元数据、停用和轮换。
- 密码重置申请列表、处理和一次性临时密码展示。
- 用户列表：账号、状态、角色、创建时间、最近登录、用量摘要。
- 任务列表：用户、工作区、状态、耗时、错误类别，不默认展示文件内容。
- 账号启用/停用和审计记录。

不在第一批做复杂运营报表、代用户编辑报告或任意浏览用户内容。

## 10. 数据库与存储设计

### 10.1 表设计总览

| 表 | 是否需要 | 主要用途 |
| --- | --- | --- |
| `users` | 必须 | 用户、角色、密码状态 |
| `auth_sessions` | 必须新增 | 可撤销 Session |
| `invite_codes` | 必须 | 注册邀请码 |
| `password_reset_requests` | 必须 | 人工重置流程 |
| `workspaces` | 必须 | 用户工作区 |
| `workspace_files` | 必须 | 工作区与文件关联、角色、标签 |
| `file_relations` | 必须 | 关系候选和用户确认 |
| `task_files` | 必须新增 | 任务输入文件快照，替代 `file_ids_json` |
| `task_clarifications` | 第一批必须 | 追问与回答审计 |
| `task_plans` | 必须 | 版本化计划和确认 |
| `task_steps` | 必须 | 队列、步骤、attempt、进度、重试 |
| `task_events` | 必须新增 | SSE 事件持久化 |
| `agent_runs` | 必须 | 执行版本、模型预算和结果 |
| `reports` | 必须 | 报告版本和状态 |
| `report_assets` | 必须 | 图表、DOCX、PDF 和其他资产 |
| `user_feedback` | 第二批必须 | 点赞、纠错、重生成原因 |
| `prompt_versions` | 第二批必须，第一批可预留引用 | Prompt 内容版本和评估绑定 |
| `audit_logs` | 必须新增 | 管理操作和敏感动作审计 |

### 10.2 主要字段与关联

#### `users`

- `id`、`username_normalized`（唯一）、`display_name`；
- `password_hash`；
- `role`、`status`；
- `must_change_password`、`temporary_password_expires_at`；
- `failed_login_count`、`locked_until`、`last_login_at`；
- `created_at`、`updated_at`、`deleted_at`。

禁止返回：`password_hash`、失败登录内部计数细节、锁定策略内部字段。

#### `auth_sessions`

- `id`、`user_id`、`token_hash`（唯一）；
- `expires_at`、`last_seen_at`、`revoked_at`；
- `ip_hash`、`user_agent_summary`、`created_at`。

禁止返回：`token_hash`。

#### `invite_codes`

- `id`、`code_hash`、`label`、`status`；
- `max_uses`、`used_count`、`expires_at`；
- `created_by`、`created_at`、`updated_at`。

禁止列表返回：`code_hash` 和原始码。

#### `password_reset_requests`

- `id`、`user_id`（可空，防账号枚举场景）、`account_fingerprint`；
- `status`、`reason`、`requested_at`；
- `handled_by`、`handled_at`、`resolution_note`。

不保存临时密码明文。

#### `workspaces`

- `id`、`owner_user_id`；
- `name`、`description`、`status`；
- `created_at`、`updated_at`、`archived_at`、`deleted_at`。

当前第一批一个工作区只有一个 owner，不引入成员表。

#### `files`（调整现有表）

- 保留 `id`、原文件名、类型、摘要和时间。
- 新增 `owner_user_id`、`storage_backend`、`object_key`、`size_bytes`、`mime_type`、`sha256`、`version`。
- 将单一 `status` 拆为生命周期、解析和理解状态。
- `file_path` 仅作为迁移期内部字段，后续移除；API 立即停止返回。
- `schema_json` 迁移期保留，逐步变成结构摘要；大块文本进入 `file_chunks`，资产进入存储层。

#### `workspace_files`

- `workspace_id`、`file_id`（联合唯一）；
- `role`、`role_source`、`role_confidence`、`role_reason`；
- `tags_json`；
- `user_confirmed_at`、`created_at`。

#### `file_relations`

- `id`、`workspace_id`、`source_file_id`、`target_file_id`；
- `relation_type`、`confidence`、`evidence_json`、`inference_method`；
- `status`、`created_by_type`、`confirmed_by_user_id`；
- `version`、`created_at`、`updated_at`。

同一有向关系按版本保存；需要对称展示的关系由服务层处理。

#### `file_chunks`（调整现有表）

- 保留 `file_id`、`chunk_index`、`chunk_text`。
- `page_number` 改为可空，以支持 Markdown/OCR。
- 新增 `source_type`、`section_path`、`char_start`、`char_end`、`chunk_hash`、`parser_version`。
- `vector_id` 作为未来外部向量索引引用，不把它当作当前已经有向量库。

#### `tasks`（调整现有表）

- 新增 `workspace_id`、`owner_user_id`；
- `title`、`original_request`、`normalized_intent_json`；
- 使用本设计状态枚举；
- `current_plan_id`、`current_run_id`、`progress_percent`、`current_stage`；
- `cancel_requested_at`、`cancelled_at`、`failure_code`；
- `created_at`、`updated_at`、`completed_at`。

迁移后不再以 `file_ids_json` 作为正式关联，不再把 `report_path` 放在任务表。

#### `task_files`

- `task_id`、`file_id`；
- `file_version`、`workspace_file_role_snapshot`；
- `relation_snapshot_json`；
- 联合唯一约束。

#### `task_clarifications`

- `id`、`task_id`、`round_no`；
- `question_json`、`answer_json`；
- `status`、`created_at`、`answered_at`。

#### `task_plans`

- `id`、`task_id`、`version`；
- `status`：`draft`、`confirmed`、`superseded`、`cancelled`；
- `goal_json`、`steps_json`、`constraints_json`、`estimated_budget_json`；
- `created_by`、`confirmed_by_user_id`、`confirmed_at`；
- `created_at`。

计划步骤的可执行副本在确认后写入 `task_steps`。

#### `task_steps`

- `id`、`task_id`、`plan_id`、`agent_run_id`；
- `step_key`、`name`、`agent_type`、`tool_name`；
- `depends_on_json`、`input_refs_json`、`output_refs_json`；
- `status`、`progress_percent`、`attempt`、`retry_of_step_id`；
- `idempotency_key`；
- `available_at`、`lease_owner`、`lease_expires_at`；
- `started_at`、`finished_at`、`latency_ms`；
- `error_code`、`error_message_safe`。

#### `agent_runs`

- `id`、`task_id`、`plan_id`、`run_number`；
- `status`、`trigger_type`（首次、局部重试、从计划重跑）；
- `input_snapshot_json`；
- `model_provider`、`model_name`；
- `prompt_version_ids_json`；
- `model_call_limit`、`model_call_count`、`input_tokens`、`output_tokens`；
- `started_at`、`finished_at`。

#### `tool_calls`（调整现有表）

- 关联 `task_step_id`、`agent_run_id`；
- 保留 `tool_name`、状态、耗时和错误。
- 输入输出改为脱敏摘要 + 资产引用，避免无限增长。
- 模型调用可继续使用该表或拆为 `model_calls`；第一批为减少表数量可先统一记录并用 `call_type` 区分。

#### `task_events`

- `id`（单调递增，可作为 SSE event ID）、`task_id`、`event_type`；
- `stage`、`progress_percent`、`message`、`payload_json_safe`；
- `created_at`。

#### `reports`

- `id`、`task_id`、`agent_run_id`、`version`；
- `template_key`、`status`；
- `report_document_json`、`content_markdown`；
- `quality_status`、`quality_summary_json`；
- `created_at`、`finalized_at`。

#### `report_assets`

- `id`、`report_id`、`asset_type`（chart、image、docx、pdf、attachment）；
- `storage_backend`、`object_key`、`content_type`、`size_bytes`、`sha256`；
- `status`、`created_at`。

禁止返回内部 `object_key`，只返回资产 ID、类型、状态和受控下载 URL。

#### `user_feedback`

- `id`、`user_id`、`workspace_id`、`task_id`、`report_id`；
- `rating`、`feedback_type`、`comment`、`correction_json`；
- `created_at`。

#### `prompt_versions`

- `id`、`prompt_key`、`version`、`content`、`schema_version`；
- `status`、`change_note`、`created_by`、`created_at`。

Prompt 内容只允许管理员访问；对普通任务响应只返回版本号。

#### `audit_logs`

- `id`、`actor_user_id`、`action`、`target_type`、`target_id`；
- `result`、`metadata_json_safe`、`created_at`。

不记录密码、邀请码原文、Session 或 API Key。

### 10.3 现有四表迁移策略

1. 先引入 Alembic 并基线化现有结构，不直接手改 SQLite。
2. 新增用户/工作区/权限表和可空归属字段。
3. 通过部署时显式配置的迁移管理员创建“旧数据隔离工作区”；不能硬编码账号或密码。
4. 将现有 7 个文件和 16 个任务关联到该隔离工作区，或在管理员确认前保持不可被普通用户访问。
5. 双读迁移：优先读新关联表，缺失时只在受控兼容层读 `file_ids_json`。
6. 双写稳定后停止写 `file_ids_json`、`report_path` 和新的绝对 `file_path`。
7. 最后一个独立版本再删除旧字段，避免一次性破坏当前运行。

本阶段不执行上述迁移。

### 10.4 API 中去除本地路径

当前 `FileResponse.file_path` 和报告 `report_path` 不应继续返回。V2 响应改为：

```json
{
  "id": 12,
  "filename": "sample.xlsx",
  "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "size_bytes": 102400,
  "status": "ready",
  "download_url": "/api/v2/files/12/download"
}
```

下载接口再次校验当前用户和工作区归属后流式返回，或生成短期签名地址。图表不再通过全局 `/static/charts/...` 裸路径访问。

### 10.5 SQLite、生产数据库和对象存储

本地开发：

- SQLite + 本地存储适配器；
- 单 API、单 worker；
- 开启合理的 busy timeout，必要时使用 WAL；
- 每日文件级备份并验证恢复。

低并发单机生产：

- 仍可使用 SQLite，但 API 和 worker 必须共享同一持久卷且不能多机横向扩容；
- 所有写事务保持短小；
- 备份数据库、上传文件和报告资产，三者必须保持同一恢复点或有补偿策略。

规模增加后：

- 数据库通过 `DATABASE_URL` 切换 PostgreSQL；
- 存储通过 `StorageAdapter` 从 `LocalStorage` 切换 `ObjectStorage`；
- 数据库只保存 `object_key` 和元数据，不保存供应商完整 URL；
- 后台迁移对象时先复制、校验 SHA-256、切换引用，再清理旧对象。

### 10.6 删除与清理

- 默认使用软删除，先阻止新访问和新任务。
- 运行中的任务先请求取消。
- 保留期到达后按资源清单逐个删除对象、chunks、关系、步骤、事件、报告资产和主体记录。
- 删除任务必须可重入，记录每个对象结果，避免删除一半后无法恢复。
- 审计日志保留最小匿名化记录，不保留文件内容。
- 具体保留期、账号删除后的冷静期和备份清除周期必须由产品负责人确认。

## 11. API 设计

所有 V2 业务接口使用 `/api/v2`。列表接口统一支持 `limit`、`cursor` 和必要筛选；错误响应统一包含安全的 `code`、`message`、`request_id`，不返回堆栈或路径。

### 11.1 当前接口处置

| 当前接口 | 建议 | 原因 |
| --- | --- | --- |
| `GET /api/health` | 保留 | 健康检查仍需要，可增加不含敏感信息的版本/依赖状态 |
| `POST /api/files/upload` | 修改并迁移到工作区作用域 | 需要登录、批量上传、自动处理、归属和路径脱敏 |
| `GET /api/files` | 废弃全局形式 | 必须按工作区/用户查询 |
| `GET /api/files/{id}` | 修改 | 加归属校验，返回结构化理解结果，不返回路径 |
| `POST /api/files/{id}/parse` | 新 UI 废弃，兼容期保留 | 上传后自动处理，解析成为后台工具 |
| `POST /api/files/{id}/analyze` | 新 UI 废弃 | 分析应由确认后的计划驱动 |
| `POST /api/files/{id}/charts` | 新 UI 废弃 | 图表应是任务步骤资产 |
| `POST /api/files/{id}/index` | 新 UI 废弃 | 索引应是统一文件处理的一部分 |
| `POST /api/files/{id}/search` | 修改 | 支持工作区多文件检索与标准引用 |
| `POST /api/files/{id}/ocr` | 新 UI 废弃 | OCR 应由文件处理或计划自动调用 |
| `POST /api/tasks` | 语义重做 | 只创建 draft/启动完整性检查，不同步执行 |
| `GET /api/tasks` | 修改 | 工作区作用域、分页、状态筛选和权限 |
| `GET /api/tasks/{id}` | 修改 | 返回计划、阶段、进度和报告摘要 |
| `GET /api/tasks/{id}/trace` | 兼容后由 events/runs 替代 | 现有轨迹粒度不足且缺少实时游标 |
| `POST /api/tasks/{id}/report` | 废弃手工裸生成 | 报告由正式执行和 Report Agent 生成 |
| `GET /api/reports/{task_id}` | 修改为报告资源 ID | 一个任务可有多个执行和报告版本 |
| `GET /api/reports/{task_id}/download` | 修改 | 按报告/资产 ID 下载 DOCX/PDF，执行归属校验 |
| `/static/charts/...` | 废弃公开形式 | 图表属于受保护报告资产 |

兼容期旧接口应标记 deprecated，新前端只调用 `/api/v2`。

### 11.2 Auth 与用户

| 方法与路径 | 用途 | 登录/权限 | 主要请求 | 主要响应 |
| --- | --- | --- | --- | --- |
| `POST /api/v2/auth/register` | 邀请注册 | 否 | `username`、`password`、`invite_code` | 用户安全字段、Session 状态 |
| `POST /api/v2/auth/login` | 登录 | 否 | `username`、`password` | 用户安全字段；Cookie 写 Session |
| `POST /api/v2/auth/logout` | 撤销当前 Session | 用户 | 无 | `success` |
| `GET /api/v2/auth/me` | 当前登录信息 | 用户 | 无 | `id`、账号、显示名、角色、密码状态 |
| `POST /api/v2/auth/password-reset-requests` | 申请重置 | 否 | `username`、可选说明 | 通用受理信息 |
| `POST /api/v2/auth/change-password` | 修改密码/临时密码转正 | 用户 | `current_password`、`new_password` | `success`，并撤销其他 Session |
| `GET /api/v2/users/me` | 个人设置和用量 | 用户 | 无 | 资料、配额摘要、创建时间 |
| `PATCH /api/v2/users/me` | 修改显示名等非敏感资料 | 用户 | `display_name` | 更新后的安全字段 |
| `GET /api/v2/users/me/sessions` | 查看会话 | 用户 | 无 | 会话 ID、时间、设备摘要 |
| `DELETE /api/v2/users/me/sessions/{session_id}` | 撤销会话 | 用户 | 无 | `success` |

### 11.3 管理员

| 方法与路径 | 用途 | 登录/权限 | 主要请求 | 主要响应 |
| --- | --- | --- | --- | --- |
| `GET /api/v2/admin/invite-codes` | 邀请码列表 | 管理员 | 状态/分页 | 标签、状态、次数、有效期 |
| `POST /api/v2/admin/invite-codes` | 创建邀请码 | 管理员 | 标签、有效期、次数 | 原始码仅本次返回一次 |
| `PATCH /api/v2/admin/invite-codes/{id}` | 修改元数据/状态 | 管理员 | 标签、有效期、次数、状态 | 安全字段 |
| `POST /api/v2/admin/invite-codes/{id}/rotate` | 轮换邀请码 | 管理员 | 新策略 | 新原始码仅一次返回 |
| `GET /api/v2/admin/password-reset-requests` | 查看申请 | 管理员 | 状态/分页 | 申请、用户基本信息 |
| `POST /api/v2/admin/password-reset-requests/{id}/resolve` | 生成临时密码或拒绝 | 管理员 | `action`、备注 | 临时密码仅批准时一次返回 |
| `GET /api/v2/admin/users` | 用户基本状态 | 管理员 | 状态/分页 | 用户元数据和用量摘要 |
| `PATCH /api/v2/admin/users/{id}/status` | 启停账号 | 管理员 | `status`、原因 | 更新结果 |
| `GET /api/v2/admin/tasks` | 任务基本状态 | 管理员 | 用户/状态/时间筛选 | 状态、耗时、错误类别、用量 |
| `GET /api/v2/admin/audit-logs` | 管理操作审计 | 管理员 | 类型/时间/分页 | 脱敏审计事件 |

### 11.4 工作区

| 方法与路径 | 用途 | 登录/权限 | 主要请求 | 主要响应 |
| --- | --- | --- | --- | --- |
| `POST /api/v2/workspaces` | 新建工作区 | 用户 | `name`、`description` | 工作区 |
| `GET /api/v2/workspaces` | 历史工作区列表 | 用户 | 状态/游标 | 仅当前用户工作区摘要 |
| `GET /api/v2/workspaces/{id}` | 工作区详情 | owner | 无 | 概况、文件/任务/报告计数 |
| `PATCH /api/v2/workspaces/{id}` | 改名、描述、归档 | owner | 可变字段 | 更新后工作区 |
| `DELETE /api/v2/workspaces/{id}` | 请求删除 | owner | 确认字段 | 删除任务 ID/状态 |

### 11.5 文件、理解与关系

| 方法与路径 | 用途 | 登录/权限 | 主要请求 | 主要响应 |
| --- | --- | --- | --- | --- |
| `POST /api/v2/workspaces/{id}/files` | 单个/批量上传 | owner | multipart 文件 | 文件资源列表、处理状态，`202` |
| `GET /api/v2/workspaces/{id}/files` | 文件列表 | owner | 类型/状态/角色/游标 | 脱敏元数据、摘要状态 |
| `GET /api/v2/workspaces/{id}/files/{file_id}` | 文件详情 | owner | 无 | 元数据、结构、摘要、角色、标签 |
| `PATCH /api/v2/workspaces/{id}/files/{file_id}` | 修改角色/标签 | owner | `role`、`tags`、确认信息 | 更新结果 |
| `POST /api/v2/workspaces/{id}/files/{file_id}/processing-retries` | 重试文件处理 | owner | 可选失败阶段 | 新 attempt、状态 |
| `GET /api/v2/workspaces/{id}/files/{file_id}/download` | 下载原文件 | owner | 无 | 受控文件流/短期地址 |
| `DELETE /api/v2/workspaces/{id}/files/{file_id}` | 从工作区移除/请求删除 | owner | 删除范围确认 | 状态 |
| `POST /api/v2/workspaces/{id}/file-relations/infer` | 重新推断关系 | owner | 文件 ID 范围 | 候选任务/候选列表 |
| `GET /api/v2/workspaces/{id}/file-relations` | 查看关系候选 | owner | 状态/类型 | 关系、证据、置信度 |
| `PATCH /api/v2/workspaces/{id}/file-relations/{relation_id}` | 确认、拒绝或修改 | owner | 状态、类型、键映射、备注 | 新关系版本 |
| `POST /api/v2/workspaces/{id}/search` | 工作区文档检索 | owner | 查询、文件范围、top_k | 事实候选和标准引用 |

### 11.6 任务、追问、计划与进度

| 方法与路径 | 用途 | 登录/权限 | 主要请求 | 主要响应 |
| --- | --- | --- | --- | --- |
| `POST /api/v2/workspaces/{id}/tasks` | 创建 draft 并检查完整性 | owner | `request`、文件 ID、输出要求 | 任务、当前状态、追问或计划状态 |
| `GET /api/v2/workspaces/{id}/tasks` | 历史任务 | owner | 状态/时间/游标 | 任务摘要 |
| `GET /api/v2/tasks/{task_id}` | 任务详情 | owner | 无 | 状态、阶段、进度、当前计划/run/报告 |
| `GET /api/v2/tasks/{task_id}/clarifications` | 查看追问 | owner | 无 | 轮次、问题、回答状态 |
| `POST /api/v2/tasks/{task_id}/clarifications/{id}/answer` | 回答追问 | owner | 结构化答案 | 新任务状态 |
| `GET /api/v2/tasks/{task_id}/plans` | 计划版本 | owner | 无 | 计划摘要和状态 |
| `GET /api/v2/task-plans/{plan_id}` | 计划详情 | owner | 无 | 步骤、依赖、预算、限制 |
| `PATCH /api/v2/task-plans/{plan_id}` | 修改计划草稿 | owner | 文件范围、允许参数、步骤启用、输出要求 | 新计划版本 |
| `POST /api/v2/task-plans/{plan_id}/confirm` | 确认并入队 | owner | 可选确认备注 | `queued` 任务/run |
| `POST /api/v2/tasks/{task_id}/cancel` | 取消等待或执行中的任务 | owner | 可选原因 | 取消请求和当前状态 |
| `GET /api/v2/tasks/{task_id}/events` | SSE 实时进度 | owner | `Last-Event-ID` | 事件流 |
| `GET /api/v2/tasks/{task_id}/events/history` | 轮询降级/历史事件 | owner | `after_id` | 增量事件 |
| `GET /api/v2/tasks/{task_id}/steps` | 查看执行步骤 | owner | run ID | 步骤、attempt、进度、错误 |
| `POST /api/v2/task-steps/{step_id}/retries` | 用户发起局部重试 | owner | 重试原因、是否复用上游 | 新 attempt |
| `POST /api/v2/tasks/{task_id}/reruns` | 从已有计划重新执行 | owner | plan ID、输入快照策略 | 新 agent run |
| `GET /api/v2/tasks/{task_id}/runs` | 查看执行版本 | owner | 无 | run、模型用量、状态 |
| `GET /api/v2/tasks/{task_id}/trace` | 兼容的人类可读轨迹 | owner | run ID | 脱敏步骤/工具/模型摘要 |

### 11.7 报告、导出与反馈

| 方法与路径 | 用途 | 登录/权限 | 主要请求 | 主要响应 |
| --- | --- | --- | --- | --- |
| `GET /api/v2/workspaces/{id}/reports` | 工作区报告列表 | owner | 状态/游标 | 报告版本摘要 |
| `GET /api/v2/reports/{report_id}` | 报告预览 | owner | 无 | 结构化内容、Markdown、引用、质量状态 |
| `POST /api/v2/reports/{report_id}/exports` | 创建导出 | owner | `format=docx/pdf` | 导出资产状态，`202` |
| `GET /api/v2/reports/{report_id}/exports` | 查看导出状态 | owner | 无 | DOCX/PDF 资产 |
| `GET /api/v2/report-assets/{asset_id}/download` | 下载报告/图表 | owner | 无 | 受控文件流/短期地址 |
| `POST /api/v2/reports/{report_id}/feedback` | 点赞、纠错、建议 | owner | 类型、评分、评论、纠正内容 | 反馈 ID |
| `POST /api/v2/reports/{report_id}/regenerations` | 基于反馈重新生成 | owner | 反馈 ID、计划版本 | 新 run/报告 |

### 11.8 评估

| 方法与路径 | 用途 | 登录/权限 | 主要请求 | 主要响应 |
| --- | --- | --- | --- | --- |
| `POST /api/v2/admin/evaluations/runs` | 启动回归评估 | 管理员 | 数据集版本、Prompt/模型版本 | 评估 run |
| `GET /api/v2/admin/evaluations/runs` | 评估历史 | 管理员 | 状态/版本 | 指标摘要 |
| `GET /api/v2/admin/evaluations/runs/{id}` | 评估详情 | 管理员 | 无 | 分类指标、失败样例、成本 |
| `GET /api/v2/admin/evaluations/datasets` | 数据集目录 | 管理员 | 无 | 版本、样例数、覆盖类别 |

评估接口不允许普通用户触发大规模模型调用。

## 12. 前端信息架构

### 12.1 路由建议

```text
/login
/register
/password-reset

/app/workspaces
/app/workspaces/new
/app/workspaces/:workspaceId
/app/workspaces/:workspaceId/files
/app/workspaces/:workspaceId/understanding
/app/workspaces/:workspaceId/tasks/new
/app/workspaces/:workspaceId/tasks
/app/tasks/:taskId/clarification
/app/tasks/:taskId/plan
/app/tasks/:taskId/run
/app/tasks/:taskId/trace
/app/reports/:reportId
/app/settings

/admin
/admin/invite-codes
/admin/password-resets
/admin/users
/admin/tasks
/admin/evaluations
/admin/audit-logs
```

V2 应使用真实 URL 路由，支持刷新恢复、深链接、浏览器前进/后退和权限守卫。

### 12.2 页面职责

| 页面 | 核心内容 |
| --- | --- |
| 登录 | 账号、密码、登录、注册链接、重置申请链接 |
| 注册 | 账号、密码、确认密码、邀请码 |
| 密码重置申请 | 账号、说明和通用提交结果 |
| 工作区列表 | 名称、更新时间、文件/任务/报告数、状态 |
| 新建工作区 | 名称、描述、可选目标 |
| 工作区详情 | 工作区概况、最近文件、最近任务、最近报告、下一步引导 |
| 文件管理 | 批量上传、解析状态、失败重试、下载、角色和标签 |
| 文件理解与关系确认 | 摘要、结构、角色、关系候选、证据、置信度、确认/拒绝/编辑 |
| 需求输入 | 选择文件、输入目标、输出要求和可选模板 |
| Agent 追问 | 分轮显示问题、回答、返回修改原需求 |
| 执行计划确认 | 目标、文件、关系、步骤、预算、限制；确认、修改、取消 |
| 实时执行 | 阶段、总进度、当前步骤、取消、错误与降级 |
| Agent 执行轨迹 | Agent/工具/模型调用摘要、耗时、attempt、错误；不展示思维链 |
| 报告预览 | 章节导航、图表、引用、异常、建议、限制、质量状态 |
| 导出 | Word/PDF 生成状态和下载 |
| 历史任务 | 按工作区、状态、时间筛选；进入任务/run/报告 |
| 个人设置 | 显示名、修改密码、Session、用量 |
| 管理员后台 | 邀请码、重置申请、用户/任务状态、评估和审计 |

### 12.3 主导航

登录后一级导航建议只保留：

- 工作区；
- 历史任务；
- 个人设置；
- 管理后台（仅管理员）。

文件、理解、任务和报告都在工作区上下文中完成，避免当前“文件页”和“工作区页”各自维护一份全局文件状态。

### 12.4 关键导航流程

新用户：

```text
注册 → 工作区列表空状态 → 新建工作区 → 上传文件
→ 文件理解/关系确认 → 输入需求 → 追问（可选）
→ 确认计划 → 实时执行 → 报告预览 → Word/PDF 导出
```

历史用户：

```text
登录 → 工作区列表 → 工作区详情
→ 查看旧文件/任务/报告
→ 修改关系或新增文件
→ 从已有计划重新执行
```

失败恢复：

```text
实时执行/历史任务 → 失败步骤
→ 查看安全错误和可重试说明
→ 局部重试或从计划重新执行
```

页面必须区分：

- 文件已上传但未解析；
- 已解析但关系未确认；
- 计划待确认；
- 任务排队/执行/审核；
- 分析完成但导出仍在生成。

## 13. 质量评估与回归测试

### 13.1 指标定义

| 指标 | 建议定义 |
| --- | --- |
| 文件解析成功率 | 合法基准文件中，输出满足类型 schema 且关键字段正确的比例 |
| 文件关系识别准确率 | 对候选关系计算 precision、recall、F1；连接键单独计算准确率 |
| 任务分类准确率 | 任务意图和是否需要追问的分类准确率 |
| 计划完整率 | 必需步骤、输入、输出、验收条件和限制全部存在的任务比例 |
| 工具调用成功率 | 合法调用成功数 / 总合法调用数；瞬时失败和业务拒绝分开统计 |
| 多文件分析正确率 | 人工金标结论和确定性数值检查共同通过的任务比例 |
| RAG 引用命中率 | 正确引用覆盖的金标事实数 / 金标事实数，同时统计引用 precision |
| 无依据拒答准确率 | 不可回答样例中正确拒答比例，并同时统计可回答样例的误拒答率 |
| 报告字段完整率 | 模板必填字段通过数 / 必填字段总数 |
| 数字一致性 | 报告数字与工具输出逐项一致的比例，关键数字要求 100% |
| Quality Review 拦截率 | 缺陷报告被拦截比例；必须同时看误拦截率，不能只追求高拦截率 |
| 任务完成时间 | P50、P95，总时长和各阶段时长 |
| DeepSeek 调用次数和成本 | 每任务调用数、成功/失败/重试、输入输出 Token、按当期计费配置估算成本 |
| 用户反馈 | 点赞率、纠错率、重生成率、主要问题类别 |

Quality Review 应额外计算：

- 缺陷召回率；
- 审核精确率；
- 自动修复成功率；
- 审核导致的平均额外调用数和耗时。

### 13.2 最小测试集

以下数量是 V2 首个可用回归集的最低门槛，不代表具有统计学充分性：

| 数据集 | 最小数量 | 分类建议 |
| --- | ---: | --- |
| 文件解析 | 54 个文件 | Excel 12、CSV 10、PDF 12、图片 12、Markdown 8 |
| Excel 细分 | 包含在上项 | 多 Sheet、空 Sheet、重复列、日期、公式、缺失、中文列名、异常类型 |
| PDF 细分 | 包含在上项 | 文本 PDF 6、扫描/混合 PDF 6；短文、长文、目录、无文本 |
| 图片细分 | 包含在上项 | 清晰中文、英文、低清、旋转、截图、无文字 |
| 文件关系工作区 | 30 组 | Excel-Excel 10、Excel-PDF 8、图片-PDF/Excel 8、冲突/无关 4 |
| 任务意图 | 80 条 | 数据、文档、综合、报告、信息不足、无依据、越界、取消/重试各类 |
| RAG 问答 | 60 条 | 可回答 40、不可回答 20；每条有金标文件/页码/片段 |
| 多文件端到端 | 30 个任务 | 学生 15、求职 15；覆盖三类关系示例和失败场景 |
| 报告金标检查 | 30 份 | 结构、数字、引用、图表、限制和建议 |
| 权限安全 | 至少 25 个用例 | 双用户资源枚举、下载、SSE、取消、重试、管理员边界 |

### 13.3 测试层次

1. 单元测试：状态迁移、权限依赖、解析器、分析工具、引用映射、配额。
2. schema/契约测试：Agent 输出、API 响应、事件和报告中间结构。
3. 集成测试：真实样例文件、数据库、存储适配器、worker 领取与租约。
4. 端到端测试：注册 → 工作区 → 上传 → 确认 → 计划 → 执行 → 报告 → 导出。
5. 回归评估：固定模型/Prompt/数据集版本，比较指标和失败样例。
6. 安全测试：越权、账号枚举、上传伪装、路径泄漏、恶意 Markdown、下载权限。
7. 可靠性测试：worker 崩溃、模型超时、取消、重复请求、幂等重试、磁盘空间不足。

### 13.4 回归门禁

V2 必须实现第一批发布前建议硬门槛：

- 关键权限越权用例 100% 阻断。
- 报告关键数字一致性 100%。
- 引用不得指向不存在的文件/页码/块。
- 合法基准文件解析成功率不低于既定基线，任何下降必须有解释。
- 无依据样例不得以高置信度生成事实。
- 单任务模型调用和重试不超过预算。
- DOCX/PDF 至少经过自动结构检查和代表样例视觉核对。

## 14. 国内访问、低成本与部署约束

### 14.1 避免绑定 Vercel 或 Render

以下模块必须保持平台无关：

- 前端只依赖环境配置的 API 基址，生产优先同域相对路径。
- FastAPI 不依赖某个平台专有请求头、磁盘路径或任务机制。
- 队列不依赖平台临时后台任务。
- 数据库只通过 `DATABASE_URL` 和 repository/service 层访问。
- 文件只通过 `StorageAdapter` 访问。
- 模型只通过 `LLMGateway` 访问 DeepSeek。
- 下载只依赖资产 ID，不在数据库中保存平台域名。
- 健康检查、日志和迁移命令保持标准容器/进程形式。

### 14.2 是否适合单机部署

在 5 人以内、每月预算约 50 元且允许任务排队的前提下，单机部署是合理起点：

- 反向代理/HTTPS；
- 前端静态文件；
- FastAPI API；
- 单 worker；
- SQLite；
- 本地持久卷；
- 定时备份。

限制：

- 不能把 SQLite 文件放在多机共享网络盘并让多个实例并发写。
- API 和 worker 虽可同机，但进程职责应分离。
- OCR、PDF 和 Matplotlib 可能产生 CPU/内存峰值，worker 并发初期设为 1。
- 机器故障会同时影响 API、数据库和文件，必须有异机/异介质备份。

### 14.3 数据库、存储和 DeepSeek 解耦

- `Database URL`：SQLite/PostgreSQL 可切换。
- `StorageAdapter`：本地目录/对象存储可切换。
- `LLMGateway`：Provider、Base URL、模型、超时和预算配置化。
- Agent 只接收资源 ID 和抽象工具，不接收具体云厂商 SDK 对象。
- 模型失败时可输出确定性统计 + 模板化限制说明，但不能伪装成完整智能分析。

### 14.4 低并发成本控制

- 单 worker、有限并发和排队。
- 文件按 SHA-256 去重解析，同一文件版本复用解析结果。
- PDF/Markdown 分块和 OCR 结果持久化，避免重复处理。
- 先用规则筛选关系候选，再把少量候选交给 DeepSeek。
- 上下文只传结构摘要和命中片段，不传整文件。
- 图表按规格缓存，报告导出按报告版本缓存。
- 对长 PDF、超大图片和多工作表设置上限。
- 任务设置模型调用和 Token 预算，失败使用有边界的重试。

### 14.5 必须限流的能力

- 登录、注册、重置申请。
- 文件上传、OCR、PDF 解析和索引。
- 任务创建、重新执行、步骤重试。
- DeepSeek 调用和报告重新生成。
- DOCX/PDF 导出和大文件下载。
- 管理员评估运行。

### 14.6 生产前安全改造

- HTTPS、安全 Cookie、CSRF 防护、严格 CORS。
- 密码哈希、Session 撤销、登录限流和账号锁定。
- 全资源归属校验和权限回归测试。
- 文件扩展名 + MIME + 文件头校验；限制大小、页数、像素和解压风险。
- 文件名净化、路径隔离、受控下载，不暴露 `file_path`/`object_key`。
- 对上传内容进行恶意文件扫描或明确隔离策略。
- Markdown 渲染进行 HTML/XSS 清理。
- API Key、Session 密钥、管理员初始化信息只通过环境或密钥管理提供。
- 日志脱敏，不记录密码、邀请码、Session、API Key 和完整敏感文件内容。
- 数据库迁移、备份、恢复演练和磁盘告警。
- worker 超时、资源限制、幂等和取消测试。
- OCR 运行时、中文语言包、字体和导出环境固定并验证。
- 依赖和容器镜像安全扫描。
- 隐私说明、数据保留和删除流程。

### 14.7 最终部署阶段仍需核实

本阶段不选择云厂商、不编造价格。部署前必须核实：

1. 备案主体、目标地区、域名和备案周期。
2. 国内不同运营商和移动网络的实际可访问性。
3. 可购买实例的 CPU、内存、磁盘、带宽、持久盘和备份能力。
4. 容器镜像拉取、Python/Node 依赖源和系统包安装可用性。
5. 生产网络访问 DeepSeek API 的稳定性、配额、限速、最新模型兼容和实际计费。
6. 对象存储的国内访问、签名下载、生命周期和跨域能力。
7. 数据库备份保留、恢复时间和磁盘增长。
8. HTTPS 证书、反向代理 SSE 配置和超时。
9. Tesseract 中文语言包、字体和 PDF/DOCX 渲染依赖。
10. 用户数据保留、隐私、删除和可能涉及的合规要求。

## 15. 分阶段迁移路线

原则：

- 不一次性重写。
- 每一阶段保留现有可运行链路或提供受控兼容入口。
- 数据迁移先扩展、再回填、再切流、最后清理。
- 高风险阶段先备份和验证回滚。

### 15.1 第一批-1：身份、迁移基线和工作区边界（第一阶段）

**目标**

先解决多用户产品最基础的数据归属和迁移能力，避免后续文件、任务和报告继续产生无 owner 数据。

**涉及模块**

- Alembic 迁移基础；
- users、auth_sessions、invite_codes、workspaces；
- 认证和权限依赖；
- API 响应去除 `file_path`/`report_path`；
- 前端登录、注册、工作区列表骨架。

**数据库影响**

- 新增表；
- 为现有资源增加可空归属字段；
- 建立旧数据隔离工作区；
- 此阶段不删除旧字段。

**API 影响**

- 新增 `/api/v2/auth` 和 `/api/v2/workspaces`；
- 为 V2 文件/任务查询建立 owner 约束；
- V1 兼容接口暂时保留。

**前端影响**

- 增加认证路由和工作区壳；
- 当前三页仍可作为受控兼容页面存在。

**验收标准**

- 两个普通用户互相无法访问任何资源；
- 注册必须邀请码，登录不需要邀请码；
- Session 可撤销；
- 所有 V2 文件响应不含服务器路径；
- 旧数据只有迁移管理员可见；
- 现有健康检查和兼容演示链路仍可运行。

**回滚方式**

- 回退 V2 路由和前端入口；
- 保留新增表和可空字段，不做破坏性降级；
- 从迁移前 SQLite 备份恢复仅作为最后手段。

**风险**

- **高风险：旧数据归属和所有资源权限查询。**

### 15.2 第一批-2：统一文件处理与关系确认

> 实施状态：V2-03 已完成本节的当前同步版本。实际角色枚举、关系类型、API、
> 配额默认值和已知限制以 `docs/V2_03_FILE_UNDERSTANDING.md` 为准；异步排队解析
> 留到下一阶段，不能把当前同步接口描述为已经有后台 worker。

**目标**

自动处理五类文件，形成结构、摘要、角色和可修正关系候选。

**涉及模块**

- 存储适配层；
- 多 Sheet Excel、Markdown、PDF 块、OCR；
- File Understanding Agent；
- 文件理解与关系确认页面。

**数据库影响**

- 调整 files/file_chunks；
- 新增 workspace_files/file_relations；
- 保存处理 attempt 和解析器版本。

**API 影响**

- 工作区作用域上传、文件详情、处理重试、关系接口；
- 当前 parse/analyze/charts/index/ocr 逐步转为内部工具。

**前端影响**

- 批量上传；
- 文件状态和失败重试；
- 角色、标签和关系确认。

**验收标准**

- 54 个最小解析样例达到基线；
- Markdown 可解析；
- Excel 可展示所有 Sheet 结构；
- 所有关系显示证据和置信度，可确认/拒绝/编辑；
- 未确认连接关系不会被自动执行。

**回滚方式**

- 保留当前手动解析接口作为兼容入口；
- 新处理结果采用版本字段，不覆盖旧 `schema_json`；
- 关闭自动理解功能开关即可回退。

**风险**

- **高风险：文件解析资源消耗、OCR 环境和错误文件处理。**

### 15.3 第一批-3：计划、队列、SSE、取消与局部重试

**目标**

把同步请求内任务迁移为可确认、可观察、可取消、可重试的持久化执行。

**涉及模块**

- 状态机、任务队列接口、worker；
- 追问、计划版本、task steps、events；
- SSE 和轮询降级；
- 任务/计划/实时执行页面。

**数据库影响**

- 调整 tasks；
- 新增 task_files、task_clarifications、task_plans、task_steps、task_events、agent_runs。

**API 影响**

- `POST /api/v2/workspaces/{id}/tasks` 不再同步执行；
- 新增追问、计划确认、事件、取消、重试和 rerun。

**前端影响**

- 追问页、计划确认页、实时执行页、断线恢复。

**验收标准**

- API 创建任务快速返回；
- worker 重启后租约任务能继续被领取；
- 排队任务可立即取消；
- 运行任务在步骤边界停止；
- 失败步骤可局部重试且不重复成功上游资产；
- SSE 断线后可按事件 ID 补拉。

**回滚方式**

- 通过功能开关将兼容 V1 任务继续走同步链路；
- 新任务表只增不删；
- 不把未完成队列任务自动转回 V1。

**风险**

- **最高风险：同步到异步后的事务一致性、重复执行和取消语义。**

### 15.4 第一批-4：Supervisor、专业 Agent 和完整报告

**目标**

在受限编排中实现跨文件分析、证据综合、质量审核和完整报告。

**涉及模块**

- Supervisor；
- 5 个专业 Agent；
- 安全分析工具、跨文件检索、引用；
- 结构化报告、Word/PDF 渲染。

**数据库影响**

- 调整 tool_calls；
- 新增 reports、report_assets；
- 保存模型调用预算、引用和质量结果。

**API 影响**

- 报告版本、导出资产、受控下载；
- 兼容旧 Markdown 报告读取。

**前端影响**

- Agent 轨迹、报告预览、引用定位、Word/PDF 导出。

**验收标准**

- 三类关系示例端到端通过；
- 报告包含概述、数据质量、异常、图表、引用、综合结论、建议和限制；
- 关键数字与工具结果 100% 一致；
- 引用可定位；
- Quality Review 重试不超过上限；
- DOCX/PDF 代表样例渲染正确。

**回滚方式**

- 保留当前线性 LangGraph 作为兼容执行器；
- 新旧报告按版本区分；
- 关闭 Quality Review 自动重试和新导出，不删除报告数据。

**风险**

- **高风险：模型生成内容的证据约束、数字一致性和导出布局。**

### 15.5 第一批-5：管理闭环、评估和生产安全

**目标**

补齐密码重置、管理员最小功能、回归评估和上线安全门槛。

**涉及模块**

- 管理后台；
- 密码重置和审计；
- 评估数据集与运行器；
- 限流、配额、备份和安全测试。

**数据库影响**

- password_reset_requests、audit_logs；
- 评估结果可先保存为版本化文件和运行摘要，稳定后再单独建表。

**API/前端影响**

- 管理、评估和个人设置页面/接口。

**验收标准**

- 临时密码只展示一次且首次登录强制修改；
- 管理员所有敏感操作有审计；
- 权限、安全和 30 个端到端样例通过；
- 有备份恢复演练；
- 生产配置不含硬编码密钥。

**回滚方式**

- 关闭管理员高级页面和评估触发；
- 保留认证与审计数据；
- 不回退已经哈希的密码。

### 15.6 V2 必须实现第二批实施顺序

1. Prompt 版本记录和模型/工具成本日志。
2. 用户反馈、纠错和报告重新生成。
3. 报告模板选择。
4. 用户配额、管理员状态看板。
5. 模型调用降级策略和失败体验。
6. 上传前批量指定文件用途。

每项都应先加入评估指标，再启用到默认流程。

### 15.7 V2 正式版后续增强实施顺序

1. 对象存储迁移。
2. PostgreSQL 和专业队列后端。
3. 语义 embedding/向量存储。
4. 团队共享和更复杂权限。
5. 评估证明有价值后再增加 Agent 或 MCP。

### 15.8 可复用的现有代码

- FastAPI、SQLAlchemy、service 分层和配置读取骨架。
- 当前文件上传的 UUID 命名、分块写入和大小限制思路。
- Pandas 解析、分析和 Matplotlib 图表服务中的确定性逻辑。
- PyMuPDF 分页、file_chunks、关键词/TF-IDF 检索的基础。
- OCR 服务的封装和错误提示。
- LangGraph、AgentState、节点追踪和 LLM 降级框架。
- 当前报告章节生成逻辑中的部分内容拼装。
- React 文件上传、文件列表、任务输入、轨迹和报告组件的交互经验。
- Docker Compose、CI smoke test 和健康检查。

复用不等于原样保留：所有服务都需要加入用户/工作区作用域、资源引用、幂等和状态语义。

### 15.9 建议废弃或替换

- 全局无权限的文件、任务和报告接口。
- `FileResponse.file_path`、任务 `report_path` 和公开 `/static/charts`。
- 同步执行的 `POST /api/tasks`。
- 只使用第一个文件/第一个 Excel Sheet 的执行路径。
- 依赖关键词命中才能进入多文件分析的分类逻辑。
- 只由一个 JSON 字段承载大量解析/分析结果的做法。
- 固定线性、失败后仍继续所有节点的工作流。
- `Base.metadata.create_all()` 作为生产数据库升级方式。
- 把当前自定义 TF-IDF 描述为已经有持久化向量库。
- 只有 Markdown 且一个任务只有一个 `report_path` 的报告模型。

## 16. 主要风险与待确认事项

### 16.1 最严重的五个技术风险

1. **多租户数据隔离风险**
   当前所有数据均无 owner，任何漏加作用域的详情、下载、SSE、取消或重试接口都可能造成越权。必须以权限回归测试作为第一阶段硬门槛。

2. **同步迁移到异步后的重复执行与状态不一致**
   worker 崩溃、租约超时、重复领取、取消和重试可能重复生成资产或多次调用 DeepSeek。需要幂等键、短事务、事件和明确 attempt。

3. **文件关系误判导致错误的跨文件结论**
   错误连接键、版本关系或规则关系会让后续所有数字和建议失真。关系必须有证据、置信度和用户确认。

4. **报告的数字、引用和导出一致性**
   模型可能改写数字、引用不充分，DOCX/PDF 渲染还可能丢图表或分页错乱。必须使用结构化报告中间层、确定性数字校验和视觉回归。

5. **低预算环境下的持久化与运行可靠性**
   SQLite、本地文件、OCR、PDF、单机和外部模型共同构成单点故障。需要单 worker 限流、资源上限、异地备份、恢复演练和可替换存储/数据库接口。

补充高风险：中文 OCR 质量、当前非语义检索的召回率、DeepSeek 输出稳定性、长 PDF/大 Excel 的内存消耗、管理员密码重置流程中的临时凭证泄漏。

### 16.2 需要产品负责人确认

1. 第一批首个主场景优先级：学生课程/研究报告，还是求职岗位对比报告？
2. 首批报告是否需要固定两套模板，还是先提供一套通用完整报告？
3. 单文件大小、单工作区文件数、Excel Sheet/行数、PDF 页数、图片像素上限。
4. 用户是否允许上传简历、成绩、联系方式等敏感资料；需要怎样的隐私提示？
5. 文件、工作区、任务、报告和备份分别保留多久；删除是否有冷静期？
6. 文件关系达到什么置信度时默认展示；哪些关系必须强制人工确认？
7. 用户修改计划允许到什么粒度：只改范围和参数，还是允许重排/禁用步骤？
8. 信息不足时最多追问几轮，用户跳过追问后是否允许“带警告执行”？
9. 报告的正式用途和免责声明；是否需要学校/企业模板或页眉页脚。
10. Word/PDF 的格式要求：目录、页码、脚注、中文字体、封面、图表分辨率。
11. 管理员是否只能看元数据，还是在用户明确授权后可以查看文件内容进行排障？
12. 邀请码是单次码、多人共享码，还是两者都需要？
13. 临时密码的有效期、管理员审批依据和被拒绝后的通知方式。
14. 普通用户的存储、每日任务和模型调用配额；管理员的系统级上限。
15. 失败后自动重试与人工重试的默认次数和可接受费用。
16. 是否接受单机故障时短暂不可用，以及可接受的数据恢复点和恢复时间。
17. 域名、备案主体和预计上线日期。
18. DeepSeek 具体模型、最大上下文、调用预算和是否允许把用户资料发送到模型服务。

## 17. 最终建议

V2 不应先从“拆出更多 Agent”开始。最优先的实施顺序是：

```text
迁移基线与用户/工作区隔离
  → 统一文件理解与关系确认
  → 计划确认、队列、SSE、取消和局部重试
  → Supervisor + 专业 Agent
  → 完整报告与 Word/PDF
  → 质量评估、管理和生产安全
```

这样可以确保每个阶段都能运行、能回滚、能验证，并把 V2 的技术亮点建立在真实的数据边界、可靠执行和可核验报告上，而不是只把现有线性工作流改名为多 Agent。

## 18. V2-05 实施状态（2026-07-24）

第一批和第二批必做能力已经落到代码：

- 报告与资产正式版本、三模板、Markdown/DOCX/PDF；
- 扫描 PDF 分页 OCR；
- 反馈、纠错、复用分析重新生成；
- Prompt 持久版本和 agent run 关联；
- 统一数据库配额、管理员覆盖和使用量；
- Worker、任务、Agent、工具、模型内部指标与 readiness；
- 85 条公开合成 deterministic 评估；
- 清理 dry-run/apply、SQLite 备份与保护性恢复；
- production 配置拒绝启动门禁和安全响应头；
- 报告中心、个人使用量和管理员治理功能页。

本阶段仍明确不包含 PostgreSQL、正式对象存储、专业队列、国内云部署和最终 UI 美化。下一阶段应优先做报告阅读层级、移动端、无障碍、长表格/宽图表交互，以及管理员监控的信息架构，而不是继续扩大 Agent 数量。

## 19. V2-06 实施状态（2026-07-24）

V2 最终前端重设计已经落到代码：

- 集中设计 Token、浅色/深色/跟随系统主题和系统字体栈；
- 桌面可折叠导航、移动抽屉、统一页面头部和反馈机制；
- 认证、工作区、文件、关系、任务、报告、使用量和管理员页面统一；
- 工作区详情使用可直接访问和刷新恢复的稳定子路由；
- 新建分析使用选择文件、目标、偏好、追问、计划和执行的分步流程；
- 任务执行保持 SSE 优先、轮询降级、刷新恢复和服务端状态真相；
- 报告中心支持安全正文、目录、版本、资产、反馈和三格式鉴权下载；
- 响应式覆盖 360px、768px、1024px、1440px 基线；
- 基础语义化、键盘焦点、Dialog 焦点管理、aria-live 和 reduced motion；
- 纯逻辑测试覆盖状态、错误、配额、计划、SSE、报告、权限、秘密和主题；
- 未增加大型 UI、状态管理或 E2E 依赖，未改变后端业务与数据模型。

V2-06 仍不包含完整自动化 E2E、国内云部署、域名/DNS、PostgreSQL 和对象存储迁移。下一阶段的前端入口应保持相对 `/api/v2`，由同域反向代理承接 `/api`；部署层需重点验证 SSE 代理缓冲、Cookie/CSRF、下载响应头、HTTPS 和持久存储。
