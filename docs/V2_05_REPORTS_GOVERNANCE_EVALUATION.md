# V2-05 报告交付、治理、评估与生产安全

## 1. 范围

V2-05 在 V2-04 的持久化任务和独立 Worker 上增加正式报告版本、导出、反馈、配额、监控、评估、清理、备份与生产门禁。本阶段继续使用 SQLite 和本地 `storage`，不引入 PostgreSQL、对象存储、Redis、Celery 或正式国内部署。

## 2. 数据库迁移

新 head 为 `20260724_0006`，父 revision 为 `20260724_0005`。迁移新增：

- `reports`、`report_assets`、`user_feedback`、`prompt_versions`；
- `usage_counters`、`quota_overrides`、`model_usage_records`；
- `evaluation_datasets`、`evaluation_cases`、`evaluation_runs`、`evaluation_results`；
- `cleanup_runs`、`worker_statuses`；
- `agent_runs.prompt_name/prompt_version_id`；
- `tool_calls.step_id/agent_run_id`。

真实数据库不会自动升级。停写并备份后手工执行：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe heads
.\.venv\Scripts\alembic.exe upgrade head
```

## 3. 报告版本与资产

每个任务可有多个 `reports.version`。初次完成使用 `initial`；用户主动重新生成使用 `user_regenerate`；由反馈发起使用 `feedback_regenerate`；Worker 重试使用 `retry`。当前版本由 `tasks.report_id` 指向，新版本不覆盖旧正文。

Markdown 是规范正文。`report_assets.storage_key` 是相对于 `storage` 的不可猜测标识，API 不返回本地绝对路径。下载必须同时匹配用户、工作区、任务、报告和资产。相同报告内容与格式的重复导出复用已有 ready 资产，因此导出是幂等的。失败导出删除未完成文件并保留 failed 元数据，不产生无归属文件。

历史版本删除是逻辑替代并等待清理；当前版本或唯一可用版本不能删除。用户可以把任一仍可用的历史版本重新设为当前版本，操作会写入审计日志。

## 4. 模板与导出

受控模板集中注册在 `report_template_service.py`：

- `comprehensive_analysis`：混合资料综合分析；
- `student_research`：课程和学生调研；
- `job_application_analysis`：简历与岗位材料分析。

客户端不能上传模板代码，模板只改变章节组织，不重新计算数据。

导出格式：

- Markdown：UTF-8 规范正文；
- DOCX：`python-docx`，支持标题、正文、列表、Markdown 表格、图表与页脚；
- PDF：`reportlab`，不依赖 Microsoft Word，使用系统 Microsoft YaHei、SimSun 或 Noto Sans CJK。

Docker 镜像安装 `fonts-noto-cjk`。缺少中文字体时 PDF 导出返回明确错误。HTML、代码块和 Markdown 原始标记不会作为可执行内容处理。

## 5. 扫描 PDF OCR

PDF 首先由 PyMuPDF 提取每页文本。只有少于 `PDF_OCR_MIN_TEXT_CHARS` 的页面进入 OCR。页面以受限 DPI 渲染，并受最大页数、单页像素和总执行时间限制。成功结果以 `source_type=scanned_pdf_ocr` 写入 `file_chunks`，保留 `page_number`、文本哈希和置信度。

重复理解会替换同一文件原有 OCR 分块，避免重复。部分页面失败时保留成功页和原 Profile；Tesseract 或语言包不可用时返回 `PDF_OCR_UNAVAILABLE` 降级信息。OCR 全文不写日志，也不会自动整体发送到 DeepSeek。

环境依赖：

- Windows：安装 Tesseract，并配置 `TESSERACT_CMD`；安装 `chi_sim` 与 `eng`；
- Docker/Linux：`tesseract-ocr`、`tesseract-ocr-chi-sim`、`tesseract-ocr-eng`；
- 所有 OCR 关键结论仍需人工复核。

## 6. 反馈与重新生成

点赞、点踩只记录反馈，不触发 Agent。数字错误、引用错误、缺少内容和纠正说明经过严格 Pydantic Schema、长度和危险控制词校验。

默认重新生成复用现有 `AgentStateV2` 的分析、检索、图表和引用，然后创建新报告并执行结构化 Quality Review。用户显式选择“重新运行分析”时，任务进入现有受控重试队列；不能通过反馈指定 Agent、工具、Prompt 或任意代码。

## 7. Prompt 版本

Prompt 版本持久化为 draft、active、retired。同名 Prompt 由数据库部分唯一索引保证最多一个 active。普通用户没有 Prompt 管理接口；管理员只能查看和激活已存在且名称在安全注册表中的版本。

激活前校验内容哈希和疑似 API Key、Token、密码等敏感模式。Prompt 不能注册工具。每个 `agent_run` 记录实际 `prompt_name`、字符串版本和 `prompt_version_id`。

## 8. 配额与用量

默认值集中在 `Settings` 和 `.env.example`：

- 同时运行任务 1、每日任务 20、每日 DeepSeek 50；
- 单任务模型调用 12、工具调用 30；
- 用户文件存储 200MB、工作区文件 50、工作区 20；
- 每任务报告版本 10、每日导出 50；
- 系统同时运行任务 2。

检查点覆盖任务创建、计划确认、模型、工具、上传和导出。计数存储在数据库，不依赖进程内存。429 响应包含配额键、当前使用量、上限和重置时间。管理员免除普通每日任务、每日模型和总存储限制，但仍受单文件、单任务模型/工具预算和系统并发上限。

管理员覆盖包含有效期和备注，且写审计日志。前端不能提交任意 `user_id` 代表他人修改配额。

## 9. 监控、健康与日志

`worker_statuses` 保存 Worker 状态、心跳、当前任务、租约、启动时间和成功/失败数量。管理员摘要聚合任务排队/执行时间、状态、失败/取消/重试率，Agent 调用和 fallback，工具错误/耗时/超时，模型调用、token 与估算成本字段。

健康接口：

- `/api/health`：只表示进程存活；
- `/api/health/ready`：数据库、Alembic head、storage、Worker 心跳和必要配置；
- `/api/health/details`：开发/测试可访问，生产仅管理员。

DeepSeek 和 OCR 不可用返回 degraded；数据库、迁移、storage 或 Worker 不可用返回 not_ready。响应不包含连接密码、Key、绝对路径或堆栈。

生产启动除静态配置门禁外，还会直接检查数据库连接、Alembic 是否为 head 和 storage 是否可写；任一失败都会拒绝启动。Worker 心跳属于 readiness 门禁，不阻止 API 进程启动。

## 10. 清理与保留

```powershell
python -m app.maintenance.cleanup --dry-run
python -m app.maintenance.cleanup --apply --confirm APPLY_CLEANUP
```

默认 dry-run。服务处理过期/撤销 Session、旧密码重置请求、旧 task events/agent runs、失败且无归属上传、被替代报告资产及超过宽限期的软删除工作区。文件删除前再次检查作用域和数据库引用，逐个删除并记录 `cleanup_runs`。活跃工作区、当前报告和有效文件不会按时间静默删除。

## 11. API 概览

普通用户：

- `GET /api/v2/usage/me`；
- `GET /api/v2/report-templates`；
- 工作区任务下的 `/reports`、`/exports`、资产下载、历史版本删除；
- `POST /reports/{report_id}/current` 切换当前版本；
- `/feedback` 与 `/reports/regenerate`。

管理员：

- `/api/v2/admin/usage/summary`、`usage/users`、用户 quota；
- tasks、workers、model-usage、feedback、prompt-versions；
- evaluations datasets/runs；
- cleanup dry-run/apply。

管理员任务与反馈接口只返回运行和反馈元数据，默认不返回用户报告正文、原始文件、密码、Session Token、API Key 或未脱敏 Prompt 输入。

## 12. 当前限制

SQLite 仍只适用于单机低并发；本地 storage 不是对象存储；DOCX/PDF 是稳定业务排版而非出版级版式；OCR 质量依赖扫描质量和语言包；模型成本只保留可扩展估算字段；最终视觉美化和国内生产部署留到下一阶段。
