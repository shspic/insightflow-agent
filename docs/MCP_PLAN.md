# MCP 扩展规划

## 1. 当前状态

当前为规划，未接入正式 MCP Server。

InsightFlow Agent 目前通过后端 service 层和 LangGraph Agent 直接调用内部工具函数。后续如果需要把工具能力暴露给更多 Agent Client、桌面助手或其他系统，可以考虑封装 MCP Server。

## 2. 为什么后续可以接 MCP

MCP 适合把项目中的工具能力标准化为可发现、可调用、可审计的工具接口。对于 InsightFlow Agent 来说，文件元数据读取、表格分析、PDF 检索、OCR 和报告生成都天然适合作为工具。

接入 MCP 后，可以让不同 Agent Client 复用同一套工具，而不是只在当前 FastAPI 服务内部调用。

## 3. 适合封装为 MCP Tool 的能力

- `read_file_metadata`：读取文件 ID、文件名、类型、状态、摘要和 schema。
- `analyze_table`：对 CSV / Excel 执行数据分析，返回行列数、字段、缺失值和统计信息。
- `generate_chart`：基于表格数据生成图表并返回图表路径。
- `search_pdf_chunks`：对 PDF chunk 执行检索，返回页码、片段和分数。
- `run_ocr`：对图片执行 OCR 或读取已有 OCR 结果。
- `generate_report`：基于任务和文件结果生成 Markdown 报告。
- `list_task_history`：读取任务历史和执行轨迹。

## 4. MCP 架构草图

```text
Agent Client
  ↓ MCP 协议
InsightFlow MCP Server
  ↓
现有 service 层
  ↓
SQLite + 本地 storage
```

现有 FastAPI 后端可以继续保留，MCP Server 可以作为同一项目中的独立入口，也可以作为单独进程部署。

## 5. MCP Client / Server 的职责

MCP Client：

- 发现可用工具。
- 向 MCP Server 发送工具调用请求。
- 接收结构化工具结果。
- 决定如何组合工具和生成最终回答。

MCP Server：

- 暴露标准化工具列表。
- 校验工具输入。
- 调用现有 service 层。
- 返回结构化结果。
- 记录工具调用日志和错误。

## 6. 与现有 LangGraph Agent 如何结合

当前 LangGraph Agent 直接调用内部 Python service。后续可以把 `execute_tool` 节点改造成两种模式：

- 本地模式：继续直接调用 service 函数。
- MCP 模式：通过 MCP Client 调用 MCP Server 暴露的工具。

这样可以保留当前稳定链路，同时逐步把工具调用标准化，不需要一次性重构整个 Agent。

## 7. 为什么当前阶段没有强行实现 MCP

当前项目已经覆盖文件处理、RAG、OCR、报告、LangGraph、LLM 降级和部署。此时强行接 MCP 会增加调试范围和复杂度，也可能影响已经稳定的演示链路。

更合理的做法是先把现有工具函数、输入输出和错误结构整理清楚，再逐步封装 MCP Server。这样更符合“先稳定核心能力，再扩展协议层”的工程顺序。

## 8. 后续实现路线

1. 标准化现有工具函数
   - 明确每个工具的输入 schema、输出 schema 和错误格式。
   - 减少工具内部对 FastAPI 请求上下文的依赖。

2. 封装 MCP Server
   - 将 `read_file_metadata`、`analyze_table`、`search_pdf_chunks` 等能力暴露为 MCP Tool。
   - 保持工具返回结构清晰、可序列化。

3. Agent 通过 MCP Client 调用
   - 在 LangGraph 的 `execute_tool` 节点中增加 MCP 调用路径。
   - 保留本地 service 调用作为 fallback。

4. 增加工具权限和日志
   - 对文件读取、报告生成、OCR 等能力增加权限控制。
   - 记录 MCP 工具调用输入、输出、耗时和错误。

## 9. 面试时如何解释 MCP 规划

可以这样说明：

当前项目还没有正式接入 MCP Server，因为我优先保证了核心工具能力和 LangGraph 工作流稳定可演示。MCP 的价值在于把这些工具能力标准化，让外部 Agent Client 也能调用。后续我会先整理工具输入输出，再封装 MCP Server，最后让 LangGraph 的工具执行节点通过 MCP Client 调用工具，并保留本地调用作为 fallback。

这个规划说明项目不是只做一次性 Demo，而是有向工具平台和 Agent 工具生态扩展的空间。
