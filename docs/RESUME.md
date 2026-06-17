# InsightFlow Agent 简历材料

## 项目简历描述

InsightFlow Agent 是一个基于 FastAPI + React + LangGraph 的多模态文档与数据分析智能体平台，支持 CSV / Excel / PDF / 图片上传，并通过自然语言任务完成数据分析、图表生成、PDF 检索问答、图片 OCR、Markdown 报告生成和 Agent 执行轨迹展示。项目使用 SQLite 保存文件、任务和工具调用记录，并通过 Docker Compose 支持本地一键启动。

## 简历 Bullet

- 设计并实现多模态文档与数据分析 Agent 平台，基于 FastAPI、React、SQLite 和 LangGraph 构建“文件上传 → 工具调用 → 结果生成 → 执行轨迹展示”的完整闭环。
- 实现 CSV / Excel 解析与 Pandas 数据分析、Matplotlib 图表生成、PDF 文本分块检索问答、图片 OCR 和 Markdown 报告生成，覆盖结构化数据、文档和图片三类输入。
- 设计 Agent 可观测执行链路，记录 `classify_task`、`plan_task`、`route_tools`、`execute_tool`、`write_result`、`save_result` 等节点的输入、输出、状态、耗时和错误，便于调试和面试演示。

## 面试介绍话术

这个项目叫 InsightFlow Agent，是我做的一个多模态文档与数据分析智能体。它不是普通聊天机器人，而是围绕用户上传的文件执行任务。

用户可以上传 CSV、Excel、PDF 或图片，然后输入自然语言任务，比如“分析这个文件的数据概况”“生成图表”“总结这份 PDF”“识别这张图里的文字”“生成分析报告”。后端会通过 LangGraph 工作流完成任务分类、计划生成、工具路由、工具执行、结果整理和保存。

项目里我把 Agent 的执行过程做成了可观测链路，每一步都会写入 `tool_calls` 表，并在前端展示节点名、工具名、输入输出、状态和耗时。这样面试时可以清楚解释 Agent 每一步做了什么，而不是只展示一个最终回答。

## 技术亮点关键词

- FastAPI
- React
- SQLite
- SQLAlchemy
- LangGraph
- Agent 工作流
- 工具调用
- 执行轨迹可观测
- Pandas 数据分析
- Matplotlib 图表生成
- PDF RAG
- PyMuPDF
- OCR
- pytesseract
- Markdown 报告生成
- Docker Compose

## 这个项目是不是 Agent

是，但当前版本是一个确定性规则驱动的基础 Agent，不是接入大模型的开放式聊天 Agent。

它符合 Agent 项目的核心特征：

- 能接收自然语言任务。
- 能根据任务内容判断任务类型。
- 能生成执行计划。
- 能选择工具。
- 能调用数据分析、图表、PDF 检索、OCR、报告生成等工具。
- 能整理工具结果并返回用户可读答案。
- 能记录每一步执行轨迹。

当前版本没有接入大模型，是为了优先保证安全、可控和可解释。后续可以在分类、计划和结果生成节点逐步接入 LLM，同时保留工具调用和执行轨迹框架。

## 面试中可以主动说明的取舍

- RAG 初版使用关键词或轻量检索，优先保证功能闭环，后续可升级为向量数据库。
- OCR 依赖本机 Tesseract 配置，Docker 演示版默认不内置，避免系统包下载影响项目启动。
- 当前是单用户本地演示版，重点展示 AI Agent 应用工程能力，不是生产级 SaaS。
- Agent 不执行用户输入代码，数据分析只调用预设 Pandas 工具函数，降低安全风险。
