# V2-04 可靠任务执行层、计划确认与多 Agent 主体架构

## 1. 范围与边界

V2-04 在 V2-03 的 Profile、文件关系、Workspace Context、Cookie Session 和数据隔离之上，新增可靠任务执行闭环。正式流程为：

```text
选择文件并输入需求
→ Workspace Context
→ 最多两轮必要追问
→ Supervisor 计划草稿
→ 用户修改或确认
→ 数据库任务队列
→ 独立 Worker
→ 五个专业 Agent
→ Quality Review
→ 最多一次局部重试
→ 结构化结果和 Markdown 报告
```

本阶段不实现 Redis、Celery、RabbitMQ、PostgreSQL、对象存储、任意节点暂停后原地恢复、Word/PDF 新导出、最终视觉美化或国内生产部署。

## 2. 数据库迁移

增量迁移为 `20260724_0005`，直接基于 `20260723_0004`，不修改既有迁移。

`tasks` 复用：

- `user_input`：正式承担 `user_request`；
- `file_ids_json`：正式承担当前计划选择文件快照；
- `report_path`：继续保存当前 Markdown 内部资源定位。

新增任务字段包括当前计划/步骤、进度、取消时间、重试、排队/开始/完成/失败/心跳时间、错误、结果摘要、报告标识、Context 版本、持久化 AgentState、DeepSeek 开关、报告偏好、Worker、租约和 attempt。

新增表：

- `task_clarifications`：轮次、问题、回答和状态；
- `task_plans`：不可覆盖的版本化计划；
- `task_steps`：可恢复步骤、依赖、进度和重试；
- `task_events`：只追加事件，`task_id + id` 支持 SSE 增量恢复；
- `agent_runs`：Agent/模型/Prompt 版本、摘要、工具、耗时、状态和降级。

事件和 Agent 运行记录不保存密码、Token、API Key、完整 Prompt、完整文档或绝对路径。

## 3. 任务状态机

状态：

```text
draft
awaiting_clarification
planning
awaiting_confirmation
queued
running
reviewing
retrying
completed
completed_with_warnings
failed
cancelled
```

`task_state_machine.py` 是唯一确定性状态转换入口。非法转换拒绝；每次有效转换同时追加事件；进度限制为 0～100；完成和取消不允许回到运行。`failed` 和 `completed_with_warnings` 只能通过显式受限重试进入 `retrying`，不能直接进入 `running`。

## 4. 数据库队列和 Worker 租约

启动入口：

```powershell
python -m app.workers.task_worker
```

Worker 只认领当前计划为 `confirmed` 的 `queued` 任务。认领使用带旧状态和租约条件的单条 `UPDATE`；只有一个 Worker 的更新行数能为 1。认领后写入：

- `worker_id`；
- `lease_expires_at`；
- `heartbeat_at` / `last_heartbeat_at`；
- `attempt_number`。

运行中 Worker 定时延长租约。异常退出不会主动把任务改成失败；租约过期后，其他 Worker 可重新认领。已完成步骤保持 `completed`，幂等报告使用固定任务文件名，终态任务不会被再次认领。

SQLite 连接使用 30 秒 busy timeout。当前目标仍是单机单 Worker；未来 PostgreSQL 可替换认领 SQL，但上层队列接口不变。

## 5. 主动追问

创建草稿：

```text
POST /api/v2/workspaces/{workspace_id}/tasks/drafts
```

确定性完整性检查关注目标是否过宽、必要文件是否缺失、行级合并关系是否未确认。每轮最多三个问题，默认最多两轮。用户可回答或选择按推荐继续。达到上限后：

- 有文件时用明确假设生成计划；
- 没有必要文件时返回 `NO_SELECTED_FILES`，不伪造可执行计划。

草稿接口只读取 Workspace Context，不执行 Pandas、检索、OCR、图表或报告工具。

## 6. 计划生成、版本化与确认

Supervisor 先生成确定性基础计划；用户允许且 DeepSeek 可用时，可尝试严格 JSON 计划。非法 JSON、未知工具或 Schema 不符时只降级一次。

计划可修改：

- 目标；
- 当前工作区文件；
- 步骤标题；
- 可选步骤顺序；
- 删除/增加受支持的表格分析或文档检索步骤；
- `top_k`、`retrieval_mode`、`generate_charts` 等受控参数。

每次修改创建新版本，旧版本改为 `superseded`，不覆盖历史。服务端重新校验文件归属、Agent/工具组合、参数白名单、依赖顺序和 Quality Review 最后执行。确认后才创建 `task_steps` 并进入 `queued`。

## 7. API

```text
POST  /api/v2/workspaces/{workspace_id}/tasks/drafts
GET   /api/v2/workspaces/{workspace_id}/tasks/{task_id}
POST  /api/v2/workspaces/{workspace_id}/tasks/{task_id}/clarifications
POST  /api/v2/workspaces/{workspace_id}/tasks/{task_id}/plans/regenerate
PATCH /api/v2/workspaces/{workspace_id}/tasks/{task_id}/plans/{plan_id}
POST  /api/v2/workspaces/{workspace_id}/tasks/{task_id}/plans/{plan_id}/confirm
POST  /api/v2/workspaces/{workspace_id}/tasks/{task_id}/cancel
POST  /api/v2/workspaces/{workspace_id}/tasks/{task_id}/retry
POST  /api/v2/workspaces/{workspace_id}/tasks/{task_id}/steps/{step_id}/retry
GET   /api/v2/workspaces/{workspace_id}/tasks/{task_id}/events
GET   /api/v2/workspaces/{workspace_id}/tasks/{task_id}/events/stream
```

所有接口从 Session 获取用户，不接受客户端 owner。任务、计划、步骤、事件、报告和图表都先校验 `workspace_id + task_id + owner_user_id`。

## 8. SSE 和轮询恢复

SSE 事件使用数据库自增事件 ID。服务端支持查询参数 `after_id` 和 `Last-Event-ID`；每次循环创建短数据库 Session，不长期保持事务；空闲时发送注释 heartbeat；终态事件发出后关闭。客户端关闭连接不会取消任务。

前端优先 `EventSource`，浏览器自动携带 Cookie 和恢复 Last-Event-ID。连续连接失败后，自动改为 2.5 秒增量轮询。页面刷新后以任务详情 API 为真相恢复。

## 9. 取消与重试

等待追问、等待确认和排队任务可立即取消。运行中取消只设置 `cancellation_requested_at`；Worker 在步骤之间、工具前后和模型前后检查，当前不可中断库调用完成后尽快停止。

显式重试只允许 `failed` 或 `completed_with_warnings`：

- 默认重试失败步骤和所有下游依赖；
- 指定步骤重试要求该步骤属于当前任务且状态为 `failed`；
- 已完成且不在下游链路的上游步骤复用；
- 达到 `TASK_MAX_RETRIES` 后返回 409；
- 重试事件、步骤次数和 AgentRun 都保留。

## 10. AgentState

`AgentStateV2` 是 Pydantic Schema，固定 `state_version=2.04`。包含任务/工作区/owner、原始与澄清需求、假设、文件、Context、关系、计划、当前/完成/失败步骤、数据结论、文档证据、图表、报告章节、审核、警告、预算、最终结果和报告 ID。

旧版本明确拒绝，不静默误读。状态禁止密码、Token、API Key、secret 和绝对路径字段；大输出只保存摘要、chunk ID、asset name 或 report ID。

## 11. Supervisor

Supervisor 负责完整性判断、计划、专业 Agent 选择、依赖、预算、Quality Review 和最终决策。它不直接执行用户代码、不绕过确认、不读取跨用户文件、不调用未知工具，也不进行无限重新规划。

DeepSeek 不可用时，常见文件任务仍生成确定性基础计划，并记录 `fallback_used`；无法安全规划时返回明确错误。

## 12. 五个专业 Agent

### File Understanding Agent

读取 V2-03 Workspace Context、最新 Profile、角色、质量问题和已确认关系。图片 OCR 摘要优先来自 Profile；不重复发送完整文件，不自动确认关系。

### Data Analysis Agent

对选择的 CSV/XLSX 执行预设 Pandas 操作，XLSX 覆盖所有工作表。输出缺失、重复、字段类型、数值统计、文本 Top 5、来源文件/工作表和计算方式。超过 100000 行时使用受限样本并记录警告。图表走现有服务和鉴权资源入口。没有确认连接字段时不做行级合并。

### Document Research Agent

PDF 复用现有 RAG；Markdown 复用 `file_chunks`，按标题和字符位置引用。证据包含 `file_id`、显示名、页码或章节、chunk ID、短摘要、分数、模式和 top_k。无结果时返回 `evidence_not_found`。

### Report Agent

只使用 AgentState 的结构化数字、引用和图表生成固定 12 章节 Markdown；不自行计算数字或创造引用。报告文件按 task ID 幂等写入，重试不产生大量孤立文件。

### Quality Review Agent

先确定性检查步骤、结构化数字来源、chunk 引用、文件范围、图表文件、12 个章节、本地路径、失败步骤；随后可选 DeepSeek 只接收目标、计划、结构化结论、引用摘要和报告章节。最多触发一次局部重试；无 Key 时确定性审核仍运行。

## 13. Tool Registry

注册工具：

| 工具 | 允许 Agent |
| --- | --- |
| `workspace_context_lookup` | File Understanding |
| `preset_multi_table_analysis` | Data Analysis |
| `selected_document_retrieval` | Document Research |
| `structured_markdown_report` | Report |
| `deterministic_quality_review` | Quality Review |

每个定义包含名称、描述、允许 Agent、输入/输出 Schema、超时元数据、幂等性、取消支持、成本类别和启用状态。执行不使用字符串动态 import；任意 Shell、Python、SQL、URL 和未知工具没有注册入口。

## 14. DeepSeek 与 Prompt 版本

Provider 继续由现有 LLM 服务隔离，Key 只读环境变量。没有 Key 时应用和 Worker 可正常启动。所有模型结果先过 Pydantic Schema；非法结果降级，不无限修复。

Prompt Registry 覆盖：

```text
clarification
planning
file_understanding_agent
data_analysis_agent
document_research_agent
report_agent
quality_review
```

AgentRun 只记录 provider、model、Prompt 版本、耗时、可获得的 token usage 和输入/输出摘要，不记录完整敏感 Prompt。

## 15. 前端闭环

工作区详情新增：

- 文件选择、自然语言需求和 DeepSeek 开关；
- 追问表单与“按系统推荐继续”；
- 非 JSON 的计划编辑器；
- 目标、文件、步骤标题、可选步骤顺序、删除和增加；
- 总进度、状态、Agent、工具、步骤和事件时间线；
- SSE 状态与轮询降级提示；
- 取消、任务重试、失败步骤重试；
- 最终摘要、警告、审核结果和 Markdown 报告入口。

任务真相只在服务端，不保存到 localStorage；Session Token 仍只在 HttpOnly Cookie。

## 16. 配置

```text
WORKER_POLL_INTERVAL_SECONDS=2
WORKER_LEASE_SECONDS=120
WORKER_HEARTBEAT_SECONDS=15
TASK_MAX_RETRIES=1
AGENT_MAX_REPLAN_COUNT=1
AGENT_MAX_REVIEW_RETRIES=1
TASK_MAX_CLARIFICATION_ROUNDS=2
TASK_EVENT_HEARTBEAT_SECONDS=15
TASK_MODEL_CALL_BUDGET=12
TASK_TOOL_CALL_BUDGET=20
```

## 17. 本地启动

先人工备份并升级数据库：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
```

分别启动：

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python -m app.workers.task_worker
```

```powershell
cd D:\spir\NO2_agent\frontend
npm run dev
```

Docker Compose 提供 `backend`、`worker`、`frontend` 三个服务，不要求 Redis。

## 18. 测试

自动测试覆盖迁移往返、状态机、草稿追问、计划版本/白名单、确认、租约、Worker 幂等、事件恢复、SSE 终态、隔离、AgentState、Tool 权限、模型非法 JSON 降级、取消/重试、上游复用和确定性质量审核。测试关闭真实 LLM，不读取真实 `.env`，不修改真实数据库。

## 19. 当前限制

- 单机单 Worker，SQLite 适合五人以内低并发；
- 文件理解 API 尚未迁入 Worker；
- 长 Pandas/PDF/Tesseract 单次库调用不能强制中断；
- PDF 扫描件仍不做页面 OCR；
- 数据跨文件行级合并只在确认关系后才适合继续扩展，本阶段默认并列分析；
- 报告仍复用 `tasks.report_path`，尚无独立报告/资产版本表；
- DeepSeek token usage 仅在 Provider 返回且服务层可取得时记录；
- 不支持任意节点暂停后原地恢复。

## 20. 下一阶段入口

建议 V2-05 优先补齐独立 `reports/report_assets` 版本模型、任务与模型配额、Worker 运行指标、管理端任务可观测、固定评估集和生产安全门禁；再迁移 PostgreSQL、对象存储和专业队列。

