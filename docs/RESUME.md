# InsightFlow Agent 简历材料

## 项目名称

InsightFlow Agent：多模态文档与数据分析智能体

## 一句话项目描述

基于 FastAPI + React + LangGraph 构建的多模态文档与数据分析 Agent 平台，支持文件解析、数据分析、PDF RAG、图片 OCR、报告生成和执行轨迹可视化。

## 简历项目描述

InsightFlow Agent 是一个前后端分离的多模态文档与数据分析智能体项目，基于 FastAPI + React + SQLite 构建文件上传、解析、任务管理和结果展示能力；使用 LangGraph 编排 Agent 工作流，集成 Pandas、Matplotlib、PyMuPDF、Tesseract OCR 和轻量 RAG 检索，实现表格分析、图表生成、PDF 问答、图片文字识别、Markdown 报告生成，并通过 Docker Compose、Vercel 和 Render 完成本地与公网演示部署。

## 简历 Bullet

- 基于 FastAPI + React 构建前后端分离的多模态文档分析平台，支持 CSV / Excel / PDF / 图片上传、解析、任务执行、报告展示和公网演示访问。
- 使用 LangGraph 设计 `classify_task`、`plan_task`、`route_tools`、`execute_tool`、`write_result`、`save_result` 工作流，实现 Agent 任务编排、工具调用和执行轨迹可视化。
- 集成 Pandas、Matplotlib、PyMuPDF、Tesseract OCR 等工具，实现表格数据分析、图表生成、PDF 检索问答、图片文字识别和多文件综合分析。
- 设计 SQLite 数据模型保存文件、任务、工具调用和 PDF chunk，支持任务历史、Agent trace、RAG 引用来源和 Markdown 报告生成。
- 完成 Docker Compose 本地一键启动，并将前端部署到 Vercel、后端部署到 Render，整理 README、部署文档和面试演示材料。

## 技术关键词

- 前端：React、Vite、JavaScript、原生 fetch、组件化页面。
- 后端：FastAPI、Uvicorn、Pydantic、REST API、模块化 service 层。
- Agent：LangGraph、任务分类、计划生成、工具路由、工具执行、结果整理、执行轨迹。
- RAG：PyMuPDF、PDF 文本提取、chunk 分块、关键词检索、TF-IDF 轻量向量检索、引用来源。
- 数据分析：Pandas、openpyxl、字段识别、缺失值统计、描述性统计、文本高频值。
- OCR：pytesseract、Pillow、Tesseract OCR、OCR 环境变量配置、失败降级提示。
- 工程化：SQLite、SQLAlchemy、Docker、Docker Compose、配置系统、`.env.example`。
- 部署：Vercel、Render、CORS、`VITE_API_BASE_URL`、Render `PORT`、免费部署限制说明。

## 简历版本

### 保守版

InsightFlow Agent：基于 FastAPI + React 实现的多模态文档分析工具，支持 CSV / Excel / PDF / 图片上传、解析、表格数据分析、PDF 检索、图片 OCR、Markdown 报告生成和任务历史展示；使用 SQLite + SQLAlchemy 保存文件与任务记录，并通过 Docker Compose、Vercel 和 Render 完成本地与公网演示部署。

适合强调：后端开发、全栈开发、文件处理、数据分析工具。

### 标准版

InsightFlow Agent：基于 FastAPI + React + LangGraph 构建的多模态文档与数据分析 Agent 平台。系统支持用户上传 CSV / Excel / PDF / 图片，通过自然语言创建任务，由 LangGraph 工作流完成任务分类、计划生成、工具路由、工具执行和结果整理，并集成 Pandas、Matplotlib、PyMuPDF、Tesseract OCR、轻量 RAG 检索和 Markdown 报告生成，前端可展示任务结果和 Agent 执行轨迹。

适合强调：AI 应用开发、AI Agent 开发、RAG 应用开发。

### 强化版

InsightFlow Agent：独立设计并实现一个面向多模态文件的任务执行型 AI Agent 项目，基于 FastAPI + React + LangGraph 搭建前后端闭环，支持文件管理、表格分析、图表生成、PDF RAG、图片 OCR、多文件综合分析、LLM 可选增强、Markdown 报告生成和执行轨迹可观测。项目保留本地规则降级能力，避免无 API Key 时系统不可用，并完成 Docker Compose、Vercel + Render 部署和完整面试展示文档整理。

适合强调：AI Agent 工程化、工具调用编排、端到端项目交付能力。

## 面试时 1 分钟介绍话术

InsightFlow Agent 是我做的一个多模态文档与数据分析智能体项目。它不是普通聊天机器人，而是面向真实文件的任务执行系统。

用户可以上传 CSV、Excel、PDF 或图片，然后输入自然语言任务，比如“分析这些文件的数据概况”“生成图表”“这份 PDF 里有哪些关键依据”“识别这张图片里的文字”“整理成报告”。后端通过 LangGraph 工作流完成任务分类、计划生成、工具路由、工具执行、结果整理和保存。

项目集成了 Pandas、Matplotlib、PyMuPDF、Tesseract OCR 和轻量 RAG 检索，并用 SQLite 保存文件、任务和工具调用轨迹。前端可以展示最终结果，也可以看到每个 Agent 节点的输入、输出、状态、耗时和错误。

我对这个项目的定位是 AI 应用开发演示版，不把它包装成生产级 SaaS。它主要体现的是从文件处理、工具调用、Agent 编排、结果展示到部署上线的完整工程闭环。

## 这个项目为什么是 Agent？

它具备任务型 Agent 的核心链路：

- 接收用户自然语言任务。
- 根据任务内容和文件类型判断任务类型。
- 生成执行计划。
- 路由到合适工具。
- 调用预设工具完成数据分析、图表生成、PDF 检索、OCR 或报告生成。
- 汇总工具结果并生成中文答案。
- 记录每一步执行轨迹，前端可以查看。

它不是开放式聊天 Agent，而是更适合简历项目展示的确定性任务执行 Agent。这个取舍让系统更安全、更可控，也更容易解释每一步为什么这么做。

## 为什么没有一开始接 LLM API？

这是有意的工程取舍。

我先把文件上传、解析、分析、图表、RAG、OCR、报告生成和执行轨迹打通，保证每个工具能力真实可运行。这样即使没有 API Key，系统也能用规则分类和模板回答完成演示。

后面再接入 LLM 时，LLM 只负责增强任务理解、回答组织、RAG 回答和报告总结，不负责直接执行代码或编造工具结果。这样比一开始做聊天壳更稳定，也更能体现 AI Agent 的工程结构。

## 项目难点是什么？

1. 多类型文件统一到同一套任务系统中
   - CSV / Excel、PDF、图片的处理链路完全不同，但需要统一到文件表、任务表、工具调用表和前端展示中。

2. Agent 执行过程可观测
   - 不只是返回最终答案，还要把分类、计划、路由、工具执行、写结果、保存结果这些节点都记录下来，便于调试和面试演示。

3. 工具调用安全性
   - 数据分析只调用预设 Pandas 函数，不执行用户输入代码。
   - LLM 只参与理解和总结，不允许生成代码后自动执行。
   - 文件处理不删除、不修改原始上传文件。

4. 部署环境差异
   - 本机、Docker、Render、Vercel 的路径、端口、CORS、环境变量和 OCR 能力都不同，需要用配置系统处理差异。

5. 多文件综合分析
   - 需要按文件类型分组，分别调用表格分析、PDF 检索、OCR 和报告工具，再汇总成一个综合回答。

## 后续如何增强？

- 将轻量 TF-IDF 检索升级为 Chroma / FAISS 等持久化向量数据库。
- 增加用户登录、权限管理、任务隔离和上传配额。
- 将 SQLite 升级为 Postgres，本地 storage 升级为对象存储。
- 把长任务改为异步任务队列，提高大文件处理稳定性。
- 增加自动化测试、评估集和 Agent 工具调用回归测试。
- 支持 DOCX / PDF 报告导出。
- 增强多轮任务记忆和多文件跨文档问答能力。

## 面试中可以主动说明的限制

- 当前是单用户演示版，不是生产级 SaaS。
- Render 免费部署存在冷启动和临时存储限制。
- RAG 当前使用关键词和轻量 TF-IDF 检索，没有接入生产级向量数据库。
- OCR 依赖本机或部署环境中的 Tesseract 配置，公网环境可能受限。
- 当前没有用户登录、权限管理和复杂多轮记忆。

## 公网演示地址

- 前端：[https://insightflow-agent.vercel.app](https://insightflow-agent.vercel.app/)
- 后端：[https://insightflow-agent-spi.onrender.com](https://insightflow-agent-spi.onrender.com/)
- 健康检查：[https://insightflow-agent-spi.onrender.com/api/health](https://insightflow-agent-spi.onrender.com/api/health)
- Swagger：[https://insightflow-agent-spi.onrender.com/docs](https://insightflow-agent-spi.onrender.com/docs)
