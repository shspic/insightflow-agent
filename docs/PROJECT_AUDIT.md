# InsightFlow Agent 现状功能与架构审计

> **⚠️ 本文档为 V1 单用户演示版基线审计（2026-07-18），不代表 V2（2.0.0-rc.1）当前状态。**
>
> V2 已新增多用户认证、工作区隔离、五类文件统一理解、文件关系确认、计划确认、数据库队列、独立 Worker、SSE、五个专业 Agent、报告版本与三格式导出、配额/监控/评估/备份、全站 UI 重设计和中国内地生产部署包。
>
> 最新状态见 [README](../README.md)、[V2 实施日志](V2_IMPLEMENTATION_LOG.md) 和 [V2-08 最终发布](V2_08_FINAL_RELEASE.md)。

## 1. 审计范围与结论口径

- 审计日期：2026-07-18。
- 审计对象：`frontend/src`、`backend/app`、`backend/tests`、`docker-compose.yml`、`render.yaml`、前后端 Dockerfile、`.env.example` 与当前部署地址。
- 判断原则：以实际调用链和本次验证结果为准；文档仅作为对照，不将文件名或 README 描述视为实现证据。
- 本次未修改业务代码、数据库结构和真实 `backend/.env`，也没有创建、删除或改写业务数据。

审计时的项目是一个面向单用户演示的”文件驱动任务执行”应用：用户上传表格、PDF 或图片，调用预设工具或通过 LangGraph 任务工作流得到分析、检索、OCR、图表和 Markdown 报告。（截至 V2-08，以上描述已不再准确，参见文件顶部的声明。）

## 2. 当前用户流程

1. 在首页的“文件”标签上传 `.csv`、`.xlsx`、`.pdf`、`.png`、`.jpg` 或 `.jpeg` 文件。
2. 在文件列表执行解析；表格可额外执行分析和生成图表，PDF 可建立索引，图片可执行 OCR。
3. 切换到“工作区”，可勾选一个或多个已上传文件，输入自然语言任务并同步提交。
4. 后端创建任务记录，LangGraph 依次分类、计划、路由、执行工具、整理结果和保存结果。
5. 前端展示 `final_answer`、节点轨迹；若任务已生成报告，则展示报告内容和下载链接。
6. 在“历史”标签查看任务、轨迹，并可对已完成任务手动生成或重新生成 Markdown 报告。

补充边界：PDF 的独立检索接口存在，但前端没有独立的“输入查询词并查看搜索结果”界面；当前用户主要通过 `document_qa` 任务间接使用 PDF 检索。

## 3. 前端功能清单

### 3.1 页面与路由

项目没有 `react-router`，也没有 URL 路由。`App.jsx` 通过本地 `activePage` 状态切换以下三个页面，因此不支持深链接、刷新后保留页面或浏览器前进/后退导航。

| 页面组件 | 入口 | 主要功能 |
| --- | --- | --- |
| `Upload.jsx` | 顶部“文件”标签 | 上传、刷新文件列表、解析、表格分析、图表生成、PDF 索引、图片 OCR，以及展示文件解析结果。 |
| `Workspace.jsx` | 顶部“工作区”标签 | 多选文件、提交自然语言任务、展示当前任务结果、报告和执行轨迹。 |
| `TaskHistory.jsx` | 顶部“历史”标签 | 获取任务历史、查看单个任务详情和轨迹、手动生成/重新生成报告。 |

### 3.2 主要组件

| 组件 | 实际职责 |
| --- | --- |
| `FileUploader.jsx` | 单文件选择与上传；前端 `accept` 与后端支持类型一致。 |
| `FileList.jsx` | 文件表格、操作按钮、CSV/XLSX 解析与分析展示、图表图片展示、PDF 索引信息和 OCR 文本展示。 |
| `TaskInput.jsx` | 使用复选框选择多个文件并提交 `user_input`、`file_ids`。 |
| `AgentTrace.jsx` | 按固定节点顺序展示 `tool_calls`，JSON 输入输出可折叠。 |
| `ReportViewer.jsx` | 展示 Markdown 原文并提供下载链接。 |

### 3.3 前端已接入与未接入能力

已接入：上传、列表、解析、表格分析、图表、PDF 索引、OCR、任务创建、任务历史、执行轨迹、任务报告查看和下载。

没有独立前端入口或未被调用的后端能力：

- `GET /api/files/{file_id}`：前端一直从列表数据读取文件信息，没有调用详情接口。
- `POST /api/files/{file_id}/search`：`frontend/src/api/files.js` 提供了 `searchPdf`，但没有页面或组件调用它。
- `retrieval_mode`、`top_k`：后端搜索接口支持，前端没有选择器或搜索结果页面。
- `GET /api/reports/{task_id}`：由工作区和历史页在任务已有 `report_path` 时调用，但没有独立报告库或按报告浏览入口。

### 3.4 交互与可用性问题

- 三个页面只是状态切换，没有真实路由；链接分享、刷新恢复和浏览器导航不可用。
- 文件可在 `pending` 状态直接被选择提交任务，界面没有解释哪些任务会自动分析、哪些任务依赖已解析或已索引结果。
- PDF 只有“索引 PDF”按钮，没有显式检索框、检索模式、分数和片段列表；RAG 能力的可观察性主要在 Agent 轨迹中。
- 所有文件的解析详情在列表中直接展开，文件多、PDF 摘要长或表格字段多时页面会变得很长。
- 上传页、工作区和历史页各自拉取文件/任务，没有共享刷新状态；提交任务完成后不会自动同步上传页和历史页。
- API 基址存在三处实现：`api/config.js`、`App.jsx`、`FileList.jsx`。前两处的空值处理不同，长期容易出现配置漂移。
- 未发现重复页面组件；但 `searchPdf` 是当前唯一明确未被页面使用的前端 API 封装。

## 4. 后端功能清单

### 4.1 API 路由

| API | 用途 | 前端状态 |
| --- | --- | --- |
| `GET /api/health` | 返回服务状态和应用名称。 | 首页加载时调用。 |
| `POST /api/files/upload` | 校验扩展名与 10 MB 限制，UUID 命名保存文件并写入 `files`。 | 已调用。 |
| `GET /api/files` | 按创建时间倒序返回文件列表。 | 已调用。 |
| `GET /api/files/{file_id}` | 获取单个文件记录。 | 未调用。 |
| `POST /api/files/{file_id}/parse` | 解析 CSV、XLSX、PDF 或图片基础信息。 | 已调用。 |
| `POST /api/files/{file_id}/analyze` | 对 CSV/XLSX 执行 Pandas 数据分析。 | 已调用。 |
| `POST /api/files/{file_id}/charts` | 对 CSV/XLSX 生成三个预设类型的图表。 | 已调用。 |
| `POST /api/files/{file_id}/index` | 对 PDF 分页、切块并写入 `file_chunks`。 | 已调用。 |
| `POST /api/files/{file_id}/search` | 按 `auto`、`vector` 或 `keyword` 检索 PDF chunk。 | 未被页面调用。 |
| `POST /api/files/{file_id}/ocr` | 对图片调用 Tesseract OCR 并保存结果。 | 已调用。 |
| `POST /api/tasks` | 同步创建并执行 LangGraph 任务。 | 已调用。 |
| `GET /api/tasks` | 返回任务历史。 | 已调用。 |
| `GET /api/tasks/{task_id}` | 返回任务详情。 | 已调用。 |
| `GET /api/tasks/{task_id}/trace` | 返回按创建时间排序的执行轨迹。 | 已调用。 |
| `POST /api/tasks/{task_id}/report` | 基于已有任务生成 Markdown 报告。 | 已调用。 |
| `GET /api/reports/{task_id}` | 读取任务报告。 | 已调用。 |
| `GET /api/reports/{task_id}/download` | 下载 Markdown 报告。 | 已调用。 |
| `GET /static/charts/...` | 提供图表 PNG 静态访问。 | 由 `FileList` 图片地址间接调用。 |

### 4.2 文件类型、数据与存储

- 上传、解析支持：CSV、XLSX、PDF、PNG、JPG、JPEG。
- 数据分析和图表只支持 CSV、XLSX，且 Excel 只读取第一个工作表。
- PDF 解析使用 PyMuPDF；解析时会把逐页文本写入 `files.schema_json`，摘要只保留前 3000 个字符。
- 图片“解析”只保存基础信息；OCR 是独立接口，使用 Pillow + pytesseract，依赖外部 Tesseract 可执行程序和语言包。
- 上传文件保存到 `UPLOAD_DIR`，默认在 `backend/storage/uploads`；图表保存到 `CHART_DIR`，默认在 `backend/storage/charts`；报告保存到 `REPORT_DIR`，默认在 `backend/storage/reports`。
- 图表通过 `/static/charts` 暴露 URL；报告下载通过受控 API 提供。
- `files` 响应模型仍包含 `file_path`。保存时该字段是服务器本地绝对路径，当前会被文件列表接口返回，属于需要后续收敛的信息暴露点。

### 4.3 数据库表

| 表 | 用途 |
| --- | --- |
| `files` | 保存原始文件名、类型、存储路径、状态、摘要和解析/分析/图表/OCR/RAG 元数据 JSON。 |
| `tasks` | 保存用户输入、任务类型、关联文件 ID JSON、状态、最终回答和报告路径。 |
| `tool_calls` | 保存 LangGraph 节点和可选 LLM 调用的输入、输出、状态、耗时与错误。 |
| `file_chunks` | 保存 PDF 页码、chunk 序号和文本；`vector_id` 字段目前未被写入或使用。 |

### 4.4 实际工具能力与降级

- `data_analysis_tool`：直接读取首个关联表格文件，计算行列数、字段类型、日期列、缺失值、数值统计、文本 Top 5 和预览。
- `chart_generation_tool`：直接读取首个关联表格文件，生成缺失值柱状图、首个数值列统计图、首个文本列 Top 5 图；没有相应列时写入 `skipped` 结果。
- `file_summary_tool`：读取首个关联文件的基础字段和已有摘要，不会自动解析。
- `pdf_retrieval_tool`：首个关联 PDF 自动索引后检索 chunk，返回模板回答、页码和片段；若 LLM 可用，后续 writer 可对现有引用进行表达优化。
- `image_ocr_tool`：优先复用 `ocr_result`，没有结果时执行 OCR。
- `report_writer_tool`：生成 Markdown 文件；多文件时先调用多文件服务以补充文件结果。
- `multi_file_analysis_tool`：按表格、PDF、图片分组，表格会自动分析并在无图表时生成图表，PDF 使用用户整句作为检索查询，图片尝试 OCR。

服务层普遍将预期异常转换为业务错误并由 API 返回 `400`，解析失败会把文件标记为 `failed`。OCR 会针对未安装引擎、路径不存在和语言包缺失返回中文错误。RAG 的 `auto` 模式会在自定义 TF-IDF 计算异常时回退关键词检索。

但任务是同步执行的：一次 `POST /api/tasks` 会在请求内完成读取、OCR、图表、RAG、LLM 和报告，没有队列、取消、进度轮询或超时隔离。单个工具在多文件服务中被捕获为结果内错误时，任务状态仍可能为 `success`，因为最终状态只看 `AgentState.errors`。

## 5. Agent 架构现状

### 5.1 当前工作流

```text
START
  -> classify_task
  -> plan_task
  -> route_tools
  -> execute_tool
  -> write_result
  -> save_result
  -> END
```

`graph.py` 使用 `StateGraph` 构建上述固定线性边。每个节点由 `nodes.py` 的统一包装器记录一条 `tool_calls`，失败时把错误写入 `AgentState.errors`，但工作流不做条件分支，仍继续后续节点。

### 5.2 AgentState 与模块职责

`AgentState` 包含 `task_id`、`user_input`、`file_ids`、`task_type`、`plan`、`selected_tools`、`tool_results`、`final_answer`、`errors`。

| 模块 | 实际职责 |
| --- | --- |
| `classifier.py` | 关键词和首个文件类型分类。报告关键词优先；多文件只有同时满足文件数大于 1 且命中特定综合分析关键词时才分类为 `multi_file_analysis`。 |
| `planner.py` | 通过固定映射生成步骤文本。 |
| `router.py` | 通过固定映射选出一个预设工具名。 |
| `executor.py` | 调用安全的本地服务，不执行用户代码；单文件工具均只使用 `file_ids[0]`。 |
| `writer.py` | 将结构化工具结果拼成模板中文回答、引用和报告提示。 |
| `nodes.py` | 节点编排、轨迹记录、可选 LLM 调用、最终保存。 |

当前任务类型为：`data_analysis`、`chart_generation`、`file_summary`、`document_qa`、`image_extract`、`report_generation`、`multi_file_analysis`、`unsupported`。

### 5.3 LLM 的实际接入程度

LLM 服务已经有真实 HTTP 调用实现，读取 `LLM_ENABLED`、Provider、Model、Base URL 和 API Key；不记录 API Key。没有 Key、配置为关闭或调用失败时会返回结果对象并使用本地规则/模板。

- 分类：规则结果是 `unsupported` 且 LLM 可用时，才调用 `llm_task_classifier`。
- 计划：支持任务且 LLM 可用时，调用 `llm_planner`；返回计划只能替换文字步骤，不会新增可执行工具。
- 结果：工具成功、非 `unsupported` 且 LLM 可用时，调用 `llm_result_writer`；PDF 问答使用 `llm_rag_answer`。
- 报告：执行报告工具前可调用 `llm_report_summary`，只用作报告结论覆盖文本。

本次没有读取真实 `.env`，也没有创建会触发外部模型调用的任务。因此“调用链已实现”可以确认，“当前线上 LLM 是否已配置并实际成功调用”未验证。

### 5.4 架构判定

当前更接近“单 Agent 的工作流型 Agent”：一个共享 `AgentState` 在固定 LangGraph 中流转，路由到预设工具。它不是 Supervisor + 子 Agent，也没有独立自主的子 Agent、动态委派、并行协作或记忆体。

主要问题：

- 多文件选择并不自动意味着多文件执行。若自然语言未命中综合分析关键词，会分类为单文件任务，执行器只使用第一个文件。
- 任务分类、工具选择和计划本质仍是关键词/映射表；LLM 只辅助不明确的分类和文字整理。
- 工作流没有条件边、重试、超时、失败短路或并行扇出；每类任务通常只路由一个工具。
- 报告生成工具发生在 `write_result` 之前，报告生成任务首次产生的报告无法使用随后才生成的 `final_answer` 作为结论来源；手动重新生成报告时会使用已保存任务答案。
- 工具调用轨迹完整，但一次节点中多个内部文件操作只以摘要记录，无法精确追踪每个文件的子操作耗时。

适合后续拆分的职责：表格分析编排、PDF 检索问答、图片 OCR、报告汇总可以成为受 Supervisor 调度的专业工具/子工作流。暂不建议把固定分类、固定计划、结果模板和单一数据库存取拆成独立 Agent；这些职责没有独立决策收益，拆分会增加状态同步和失败处理复杂度。

## 6. 功能状态矩阵

| 功能 | 状态 | 代码事实与边界 |
| --- | --- | --- |
| 文件上传 | 已实现但需要优化 | 类型、10 MB、UUID 命名和数据库元数据已实现；接口返回服务器 `file_path`。 |
| Excel / CSV 解析 | 已完整实现 | Pandas 解析首个 Sheet/CSV，含字段、行列、日期尝试、缺失值、预览。未做真实样本回归测试。 |
| 数据分析 | 已实现但需要优化 | 统计、Top 5、预览已实现；只分析首个 Sheet，任务单文件路径只取首个关联文件。 |
| 图表生成 | 已实现但需要优化 | 三类预设柱状图和静态访问已实现；只取首个数值列和首个文本列。 |
| PDF RAG | 已实现但需要优化 | PDF 分页、切块、自动索引、引用模板回答已实现；独立搜索没有前端界面。 |
| 向量检索 | 部分实现或存在占位 | 自定义内存 TF-IDF 和余弦相似度可用；没有 embedding、向量库、向量持久化，`vector_id` 未使用。 |
| OCR | 部分实现或存在占位 | pytesseract 调用链及错误提示已实现；依赖 Tesseract/语言包，Docker 镜像默认未安装，线上实际能力未验证。 |
| LLM | 部分实现或存在占位 | 有 HTTP 调用、轨迹和降级；是否配置 Key、供应商兼容性和线上效果未验证。 |
| LangGraph | 已完整实现 | 线性 StateGraph 和六个节点已接入任务创建链路。 |
| 执行轨迹 | 已实现但需要优化 | 节点、输入输出、耗时、错误均入库并折叠展示；内部多文件子步骤粒度不足。 |
| 多文件分析 | 部分实现或存在占位 | UI 多选和服务分组已实现；分类命中依赖特定词，部分失败可仍标记任务成功。 |
| 报告生成 | 已实现但需要优化 | Markdown 生成、读取、下载、关联文件汇总已实现；报告生成任务的首次结论时序存在限制。 |
| 历史任务 | 已完整实现 | 列表、详情、轨迹和报告入口已实现；没有分页、筛选、删除或搜索。 |
| Docker | 已实现但需要优化 | Compose、前后端 Dockerfile 均存在；本次只验证 Compose 配置，未重新构建和完整运行。 |
| 测试 | 部分实现或存在占位 | 4 个轻量 smoke test 通过；没有真实文件、API 工作流、RAG、OCR、图表或报告回归测试。 |
| CI | 部分实现或存在占位 | GitHub Actions 定义后端 pytest 和前端构建；本次未验证 GitHub 上的实际运行记录。 |
| 公网部署 | 已实现但需要优化 | 当前 Vercel、Render、Swagger 和健康检查可访问；核心上传/任务链路未在本次公网环境执行。 |
| 国内网络访问 | 尚未实现 | 没有国内部署、镜像、CDN、网络探测或备用访问方案。 |
| 用户登录 | 尚未实现 | 无用户模型、认证或会话。 |
| 权限 | 尚未实现 | 无文件归属、授权、租户隔离或访问控制。 |
| 数据持久化 | 部分实现或存在占位 | SQLite 与本地文件目录可持久化于本地/Docker 卷；Render 免费实例本地磁盘不适合长期保存。 |
| 缓存 | 尚未实现 | 没有结果缓存、向量缓存或任务去重。 |
| 异步任务 | 尚未实现 | 所有任务在 HTTP 请求内同步执行。 |
| 评估系统 | 部分实现或存在占位 | 已有评估文档；没有基准集、自动指标、回归集或线上反馈数据。 |
| Prompt 版本管理 | 尚未实现 | Prompt 字符串散落于 `llm_service.py`，无版本、测试和变更记录。 |
| 用户反馈闭环 | 尚未实现 | 没有点赞、纠错、人工标注、失败反馈或质量采集。 |

## 7. 本次已验证内容

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 后端测试 | 通过 | 在 `backend` 使用 `.venv\\Scripts\\python.exe -m pytest`，4 项通过。存在 1 条 FastAPI/TestClient 的 Starlette 弃用警告。 |
| 前端构建 | 通过 | 在 `frontend` 执行 `npm run build`，Vite 生产构建成功。 |
| Docker Compose 配置 | 通过 | `docker compose config --quiet` 退出成功。Docker CLI 同时提示无法读取 `C:\\Users\\28432\\.docker\\config.json`，这是本机 Docker 配置权限警告。 |
| 本地健康检查行为 | 通过 | `test_health.py` 对 `/api/health` 校验 HTTP 200、`status=ok` 和 `app_name`。 |
| 公网健康检查 | 通过 | `https://insightflow-agent-spi.onrender.com/api/health` 返回 HTTP 200。 |
| 公网 Swagger | 通过 | `https://insightflow-agent-spi.onrender.com/docs` 返回 HTTP 200。 |
| 公网前端 | 通过 | `https://insightflow-agent.vercel.app` 返回 HTTP 200。 |
| 公网 CORS | 通过 | 以 `https://insightflow-agent.vercel.app` 发送预检请求，Render 返回 HTTP 200，`access-control-allow-origin` 为该域名。 |
| 前端 API 配置 | 已检查 | API 层读取 `VITE_API_BASE_URL`；无变量时按当前协议与主机拼接 `:8000`。 |
| 后端配置读取 | 已检查 | `config.py` 使用 `python-dotenv` 加载 `backend/.env`，所有关键字段都有默认值，`CORS_ORIGINS` 支持逗号分隔。 |
| 敏感/运行目录忽略 | 已检查 | `.gitignore` 覆盖 `.env`、数据库、storage、虚拟环境、Node 依赖和构建目录；当前这些敏感目标未被 Git 跟踪。 |

## 8. 本次未验证内容

- 没有上传真实样本，因此 CSV/XLSX/PDF/图片解析、分析、图表、PDF 索引、OCR 和报告没有重新执行端到端测试。
- 没有读取真实 `.env`，没有验证实际 API Key、LLM Provider、模型响应和费用控制。
- 未验证本机或 Render 容器是否安装 Tesseract 及 `chi_sim` 语言包。
- 未执行 `docker compose up --build`，只校验了 Compose 配置；镜像拉取、完整容器启动和容器内业务能力未验证。
- 未验证 GitHub Actions 的云端实际运行状态。
- 未验证国内网络连通性、移动端布局、并发、超大文件、异常文件、长 PDF 和长期存储行为。

## 9. 当前主要薄弱点

| 类别 | 当前问题 | 影响 | 优先级 | 是否建议近期处理 |
| --- | --- | --- | --- | --- |
| 业务场景与产品闭环 | 文件上传后缺少清晰的“下一步建议”和针对任务类型的引导；PDF 独立检索无入口。 | 用户难以理解何时解析、索引、OCR 或发起任务，RAG 能力不可见。 | 高 | 是，先做需求确认。 |
| Agent 架构 | 单一线性工作流，单文件工具只看第一个文件，多文件依赖关键词命中。 | 多文件任务可能静默忽略其余文件；失败不可按文件精确定位。 | 高 | 是。 |
| RAG / LLM / 工具能力 | RAG 是临时 TF-IDF，不是语义 embedding；OCR 与 LLM 运行环境效果未验证。 | 检索召回、中文 OCR、模型回答质量和成本不可量化。 | 高 | 是，先建立评估样本。 |
| 前端界面与交互 | 无 URL 路由、无独立 PDF 搜索、文件详情全部展开、状态筛选不足。 | 演示可用但复杂任务的操作效率和可解释性不足。 | 中 | 是，范围应保持小。 |
| 工程化、评估和部署 | 同步长任务、SQLite/本地存储、测试仅 smoke、CI 未核验、无缓存与可观测指标。 | 大文件、多用户、Render 重启和故障恢复风险高。 | 高 | 是，先明确演示版与目标规模。 |

## 10. 文档、配置与代码不一致点

- `AGENTS.md` 的技术栈提到 LangChain、Chroma 或 FAISS；当前 `requirements.txt` 没有这些依赖，实际代码使用 LangGraph 与自定义 TF-IDF 检索。
- `.env.example` 中的 `EMBEDDING_PROVIDER=local`、`VECTOR_STORE=chroma` 会被配置读取，但当前服务不使用它们；`file_chunks.vector_id` 同样未使用。这些是为后续向量库预留的占位配置/字段，不是已接入 Chroma 的证据。
- README 技术栈标题列出 Axios，但 `frontend/package.json` 不包含 Axios，实际所有请求均使用原生 `fetch`。README 本文已说明这一事实，标题仍可能造成误解。
- README 对“PDF RAG”和“向量检索”的描述需要理解为轻量关键词/自定义 TF-IDF，不应解读为已接入外部向量数据库或持久化 embedding。
- README 的 Docker 一键启动说明在当前用户本机可依赖已有 `backend/.env`；`docker-compose.yml` 使用 `env_file: ./backend/.env`，新的克隆环境仍需按 `.env.example` 创建本地配置文件，否则 Compose 无法读取该文件。

## 11. 下一步需求调研应重点确认的问题

1. 目标用户是谁、首个核心场景是什么：表格分析、PDF 问答、资料汇总还是报告交付？不同答案决定首页和 Agent 优先级。
2. 多文件的“综合”具体意味着什么：跨表对齐、跨文档问答、证据汇总，还是只需并列摘要？是否允许自动生成图表和 OCR？
3. 用户是否需要在上传页直接搜索 PDF，还是只通过任务输入提问？需要展示分数、检索模式和原文定位吗？
4. 任务应同步等待还是进入后台队列？可接受的文件大小、PDF 页数、任务时长和失败重试策略分别是什么？
5. 结果质量如何定义：表格统计准确性、RAG 引用正确率、OCR 可读率、LLM 幻觉率分别由谁验收？
6. 是否需要用户账号、文件隔离、历史保留期限、删除机制和隐私策略？这是从演示版走向真实使用的前提。
7. 公网部署的目标地区、成本上限和稳定性要求是什么？这决定是否优先引入国内部署、对象存储、Postgres、队列和监控。
8. LLM 在产品中应承担“表达优化”还是“自主规划”？在没有可量化评估与权限边界前，不建议扩大其工具控制范围。
