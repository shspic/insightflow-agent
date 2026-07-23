# V2-04 手动验收清单

## 1. 准备

1. 备份真实 `backend/data/app.db`。
2. 在后端执行 `alembic current` 和 `alembic heads`。
3. 人工执行 `alembic upgrade head`。
4. 分别启动 API、Worker、前端。
5. 确认浏览器网络面板没有暴露 Session Token、本地路径或模型 Prompt。

## 2. 基础任务与计划门禁

1. 登录普通用户，进入自己的工作区。
2. 选择 CSV/XLSX、PDF、图片或 Markdown，输入明确需求。
3. 创建草稿后确认状态为 `awaiting_confirmation`。
4. 在确认计划前观察 Worker，确认没有 Pandas、检索、图表或报告步骤执行。
5. 修改目标、文件、可选步骤标题和顺序，保存。
6. 确认生成新计划版本，旧版本未被覆盖。
7. 尝试通过 API 提交 `shell`、未知工具、URL 或跨工作区文件，确认返回 422/404。
8. 确认计划后状态为 `queued`。

## 3. 主动追问

1. 输入“分析”且不选择文件。
2. 确认进入 `awaiting_clarification`，每轮不超过三个问题。
3. 回答目标并选择文件，确认生成计划。
4. 重复信息不足场景，确认最多两轮。
5. 不提供必要文件且达到上限，确认给出明确错误，不生成虚假计划。
6. 选择“按系统推荐继续”，确认计划包含假设和限制。

## 4. Worker、租约和恢复

1. 只启动 API/前端，不启动 Worker；确认任务保持 `queued`，页面提示检查 Worker。
2. 启动 Worker；确认任务被认领，出现 `task_claimed`。
3. 观察 `worker_id`、心跳和租约持续更新。
4. 在步骤完成后强制结束 Worker 进程。
5. 等待租约过期，重新启动 Worker。
6. 确认已完成步骤复用，未重复生成报告或最终事件。
7. 同时启动第二个 Worker，确认同一任务没有被重复执行。

## 5. SSE 与刷新恢复

1. 执行任务时观察总进度、当前 Agent、步骤和事件时间线。
2. 刷新页面，确认通过 API 恢复任务状态。
3. 断开 SSE 后恢复网络，确认事件 ID 连续，没有重复大段事件。
4. 模拟 SSE 不可用，确认前端显示“轮询降级”且任务继续。
5. 关闭浏览器，确认任务继续由服务端 Worker 执行。
6. 终态后确认 SSE 连接关闭。

## 6. 取消

1. 在等待确认和排队阶段取消，确认立即 `cancelled`。
2. 在运行中请求取消，确认先记录取消请求。
3. 当前不可中断调用结束后，确认后续步骤不再执行。
4. 确认取消事件通过 SSE 出现。
5. 确认取消任务不能重新进入 `running`。

## 7. 失败与局部重试

1. 制造一个工具失败，确认任务进入 `failed`，错误不含堆栈和本地路径。
2. 点击失败步骤重试。
3. 确认只重置失败步骤及下游依赖；上游完成结果复用。
4. 达到重试上限后确认按钮禁用且服务端返回 409。
5. 确认每次 Agent 重试都有独立 AgentRun 和事件。

## 8. 多文件与五个 Agent

1. 选择 CSV/XLSX、PDF、图片和 Markdown。
2. 确认 File Understanding Agent 读取 V2-03 Profile/Context，而不是无条件重新解析。
3. 确认 Data Analysis Agent 给出文件、工作表、字段和计算方式。
4. 未确认连接字段时，确认没有自动行级拼接。
5. 确认 Document Research Agent 的 PDF 引用有真实页码，Markdown 有章节/字符定位。
6. 无命中时确认显示 `evidence_not_found`。
7. 确认 Report Agent 生成 12 个必需章节。
8. 确认 Quality Review 检查步骤、数字、引用、图表、章节和敏感路径。
9. 制造可修复审核问题，确认最多触发一次局部重试。

## 9. DeepSeek 降级

1. 不配置 `LLM_API_KEY`，启动 API 和 Worker。
2. 勾选 DeepSeek，确认前端提示确定性降级。
3. 确认计划、文件统计、确定性质量审核仍可工作。
4. 使用 mock 或测试环境返回非法 JSON，确认只降级一次，不无限调用。
5. 检查数据库和日志，确认没有 API Key 或完整敏感 Prompt。

## 10. 双用户隔离

用用户 A 和 B 分别创建工作区和任务，逐项验证：

- A 不能读取 B 的任务详情；
- A 不能读取 B 的计划和步骤；
- A 不能读取 B 的事件或 SSE；
- A 不能取消或重试 B 的任务；
- A 不能下载 B 的报告或图表；
- 管理员默认也不能读取普通用户原始文件。

## 11. 最终命令

```powershell
cd D:\spir\NO2_agent\backend
pytest
alembic heads
alembic current
```

使用临时 SQLite 执行：

```text
从零 upgrade head
→ downgrade 20260723_0004
→ 再次 upgrade head
```

```powershell
cd D:\spir\NO2_agent\frontend
npm run build
```

```powershell
cd D:\spir\NO2_agent
docker compose config --quiet
git diff --check
git status --short
```

