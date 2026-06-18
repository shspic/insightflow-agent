# InsightFlow Agent 项目复盘

## 1. 项目背景

InsightFlow Agent 是一个面向简历展示和面试讲解的 AI 应用项目。项目目标不是做一个普通聊天页面，而是构建一个能处理真实文件、调用工具、生成结果并展示执行过程的多模态文档与数据分析智能体。

项目覆盖 CSV / Excel、PDF、图片三类常见文件，并把数据分析、RAG、OCR、报告生成、Agent 工作流和部署串成完整闭环。

## 2. 项目目标

核心目标包括：

- 支持用户上传和管理 CSV、Excel、PDF、图片。
- 对表格文件进行解析、统计分析和图表生成。
- 对 PDF 进行文本提取、分块、检索和带引用问答。
- 对图片进行 OCR 识别，并保存识别结果。
- 使用 LangGraph 编排 Agent 工作流。
- 记录并展示 Agent 执行轨迹。
- 支持多文件综合分析和 Markdown 报告生成。
- 完成本地 Docker Compose 启动和 Vercel + Render 公网演示部署。

## 3. 项目架构

项目采用前后端分离架构：

```text
React + Vite 前端
  ↓ REST API
FastAPI 后端
  ↓
LangGraph Agent 工作流
  ↓
文件解析 / 数据分析 / 图表 / PDF RAG / OCR / 报告
  ↓
SQLite + 本地文件存储
```

前端负责上传文件、提交任务、展示结果、展示执行轨迹和报告内容。后端负责配置读取、数据库访问、文件处理、任务编排和工具执行。

## 4. 功能模块

- 文件上传与管理：支持 CSV、Excel、PDF、PNG、JPG、JPEG。
- 文件解析：表格解析字段和预览数据，PDF 提取文本，图片保存基础信息。
- 数据分析：使用 Pandas 统计字段类型、缺失值、数值统计和文本高频值。
- 图表生成：使用 Matplotlib 生成缺失值、数值列和分类 Top 5 图表。
- PDF RAG：使用 PyMuPDF 提取文本，保存 chunk，支持关键词和 TF-IDF 检索。
- 图片 OCR：使用 pytesseract + Pillow 识别图片文字。
- LangGraph Agent：通过节点完成任务分类、计划、路由、工具执行和结果整理。
- 执行轨迹：用 `tool_calls` 记录节点输入、输出、状态、耗时和错误。
- 报告生成：将任务、文件、分析、图表、PDF 引用和 OCR 结果整合为 Markdown。
- 多文件综合分析：按文件类型分组调用已有工具，并汇总生成综合回答。
- 部署：Docker Compose 本地启动，Vercel 部署前端，Render 部署后端。

## 5. 技术选型理由

- FastAPI：适合快速构建 Python API，类型提示清晰，Swagger 文档自动生成。
- React + Vite：开发体验轻量，适合快速构建演示型前端。
- SQLite + SQLAlchemy：本地演示成本低，结构清晰，后续可迁移到 Postgres。
- Pandas：表格数据分析事实标准工具，适合 CSV / Excel 统计分析。
- Matplotlib：后端生成静态图表简单直接，便于保存到本地 storage。
- PyMuPDF：PDF 文本提取能力稳定，依赖相对可控。
- pytesseract + Pillow：OCR 初版实现简单，可配置本机 Tesseract。
- LangGraph：把 Agent 流程显式拆成节点，方便可观测和后续扩展。
- Docker Compose：降低本地启动成本，适合面试演示。
- Vercel + Render：免费部署门槛低，适合公网展示。

## 6. 开发阶段回顾

项目按阶段推进，而不是一次性堆功能：

1. 搭建 FastAPI、React、SQLite 基础骨架。
2. 实现文件上传、文件列表和元数据保存。
3. 增加 CSV / Excel / PDF / 图片解析。
4. 加入 Pandas 数据分析和 Matplotlib 图表。
5. 建立任务系统和 `tool_calls` 执行轨迹。
6. 重构为基础 Agent，再迁移到 LangGraph 工作流。
7. 增加 PDF RAG、图片 OCR 和 Markdown 报告。
8. 接入 LLM 可选增强，同时保留本地规则降级。
9. 增强 RAG 检索和多文件综合分析。
10. 完成 Docker、README、部署文档和公网演示准备。

这种阶段化开发的好处是每一步都有可运行结果，问题更容易定位，也避免一开始就做过重设计。

## 7. 遇到的问题和解决方案

### Windows 下 Tesseract OCR 路径问题

问题：Windows 通过 winget 安装 Tesseract 后，PowerShell 中 `tesseract --version` 仍可能无法识别，说明可执行文件没有加入 PATH。

解决方案：在 `.env.example` 中增加 `TESSERACT_CMD` 和 `OCR_LANG`，后端从配置读取 Tesseract 路径。如果路径不存在、语言包缺失或引擎不可用，OCR 服务返回清晰中文错误，不让后端崩溃。

### Docker 拉取镜像 / Debian 源失败问题

问题：后端 Dockerfile 中安装 `tesseract-ocr`、英文语言包和中文语言包时，Debian 源曾出现 502 或下载失败，导致 Docker 构建失败。

解决方案：Docker 演示版优先保证前后端能启动，移除强制安装系统 OCR 依赖，把 OCR 作为可选能力。如果容器内没有 Tesseract，OCR 返回提示，不影响上传、分析、RAG、报告和 Agent 主流程。

### Render / Vercel 前后端 CORS 配置问题

问题：前端部署在 Vercel，后端部署在 Render，浏览器跨域请求需要后端明确允许 Vercel 域名。

解决方案：后端通过 `CORS_ORIGINS` 环境变量读取允许域名，Render 中填写真实 Vercel 地址，例如 `https://insightflow-agent.vercel.app`。前端通过 `VITE_API_BASE_URL` 指向 Render 后端。

### Vercel 环境变量没有重新部署导致前端仍连接错误地址

问题：Vercel 修改环境变量后，如果没有重新部署，前端构建产物仍会使用旧的 API 地址。

解决方案：明确记录部署步骤：修改 `VITE_API_BASE_URL` 后需要重新部署 Vercel 项目，确保新构建产物读取到正确 Render 后端地址。

### Render 环境变量 value 中误写 CORS_ORIGINS= 前缀的问题

问题：在 Render 控制台填写环境变量时，如果 key 已经是 `CORS_ORIGINS`，value 中再写 `CORS_ORIGINS=https://...`，后端实际读取到的 origin 会变成错误字符串，导致 CORS 不匹配。

解决方案：文档中明确说明 Render 环境变量要分开填写 key 和 value。key 填 `CORS_ORIGINS`，value 只填 `https://insightflow-agent.vercel.app` 或多个 origin 的逗号分隔列表。

### 免费部署环境的临时存储限制

问题：Render 免费 Web Service 的本地文件系统不适合长期保存 SQLite 数据库、上传文件、图表和报告。

解决方案：在 README 和部署文档中说明这是演示版限制，不承诺长期持久化。后续生产化方向是 Postgres + 对象存储。

## 8. 当前限制

- 当前是单用户演示版，不是生产级 SaaS。
- SQLite 和本地 storage 不适合公网长期持久化。
- OCR 依赖运行环境是否安装 Tesseract。
- RAG 使用关键词和轻量 TF-IDF，没有接入生产级向量数据库。
- 没有用户登录、权限隔离、限流和审计。
- 没有异步任务队列，大文件和长任务可能受免费实例资源限制。
- LLM 是可选增强，未配置 API Key 时使用规则和模板降级。

## 9. 后续优化方向

- SQLite 升级为 Postgres。
- 本地文件存储升级为 S3、R2 或 OSS。
- RAG 升级为 Chroma / FAISS / Milvus 等持久化向量检索。
- 增加用户登录、权限管理和任务隔离。
- 引入异步任务队列处理长任务。
- 增加自动化测试、评估集和回归测试。
- 增强 PDF 表格提取、图片表格识别和多文件跨文档问答。
- 支持 DOCX / PDF 格式报告导出。

## 10. 对求职的价值

这个项目适合展示 AI 应用开发和 AI Agent 工程化能力。它覆盖前端、后端、数据库、文件处理、工具调用、RAG、OCR、LLM 降级、LangGraph 工作流、执行轨迹和部署上线。

相比单纯聊天 Demo，它更能说明候选人理解 AI 应用不是只调用模型接口，还需要处理数据输入、工具能力、流程编排、异常降级、可观测性和部署约束。对于 AI 应用开发、AI Agent 开发、Python 后端、RAG 应用开发和全栈 AI 应用岗位，都可以作为完整项目案例。
