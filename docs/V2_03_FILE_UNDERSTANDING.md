# V2-03 统一文件理解、关系确认与 Workspace Context

> 阶段状态：代码和自动化测试已实现；真实 `backend/data/app.db` 未自动升级。

## 1. 范围

V2-03 在 V2-02 的认证与工作区隔离基础上实现：

- CSV、XLSX、PDF、PNG、JPG、JPEG、WEBP、MD、MARKDOWN 的统一上传和理解；
- 版本化文件 Profile；
- 系统角色/标签建议与用户确认；
- 工作区内文件关系候选、确认、拒绝和修正；
- 后续 Supervisor 可读取的版本化 Workspace Context；
- 工作区前端操作；
- 上传安全、配额和对应自动化测试。

本阶段没有实现 Supervisor、专业子 Agent、任务队列、SSE、计划确认、主动追问或新的 DOCX/PDF 导出。

## 2. 统一处理架构

同步入口为：

```python
understand_file(
    db,
    file_id=file_id,
    workspace_id=workspace_id,
    owner_user_id=user_id,
    options=options,
)
```

确定性流程：

```text
owner + workspace + association 权限校验
→ 文件存在性与支持类型检查
→ validating
→ 类型专用确定性解析
→ parsing
→ 结构、统计和质量检查
→ profiling
→ 可选 DeepSeek 语义增强
→ Pydantic Schema 校验
→ 持久化新 Profile 版本
→ ready / failed / unsupported
```

上传成功只表示文件安全保存，状态为 `uploaded`。理解阶段使用
`validating`、`parsing`、`profiling`、`ready`、`failed`、`unsupported`。
当前接口同步执行，但阶段、Profile 和 Processing Run 不依赖请求内局部变量，
可以在后续迁移到队列。

## 3. 数据库

迁移：

```text
20260723_0004_v2_file_understanding.py
```

### 3.1 `file_profiles`

每次理解生成新版本，唯一键为：

```text
(workspace_id, file_id, profile_version)
```

主要字段：

- 状态、文件类别、检测 MIME、语言、标题和摘要；
- `structure_json`、`statistics_json`、`quality_issues_json`；
- `suggested_role`、`confirmed_role`、系统标签、置信度；
- parser/model/prompt 版本、模型耗时和降级标记；
- 脱敏错误码与错误信息；
- 创建、更新和完成时间。

默认查询同一工作区文件的最大 `profile_version`。旧版本保留，重新理解不会
覆盖历史。用户确认角色的真源仍是 `workspace_files.user_confirmed_role`；
新 Profile 只复制该确认值，因此模型或规则重跑不会静默覆盖用户决定。

### 3.2 `file_relations`

关系状态：

- `suggested`
- `confirmed`
- `rejected`
- `superseded`

关系类型：

- `same_dataset`
- `continuation`
- `comparison`
- `reference_rule`
- `supporting_document`
- `derived_from`
- `image_evidence`
- `unrelated`
- `custom:<用户文本>`

当前有效关系对 `(workspace, source, target, type, direction)` 使用部分唯一索引。
对称关系规范为较小文件 ID 在前、`bidirectional`，避免正反方向重复。
修正关系时旧记录改为 `superseded`，新记录通过
`supersedes_relation_id` 保留审计链。确认和拒绝不会被重跑覆盖。

文件从工作区移除时，该工作区内以它为端点的关系被清理；关系查询和修改还会
再次验证两个端点仍属于工作区。工作区软删除后，owner 查询直接拒绝访问。

### 3.3 `file_processing_runs`

保存文件、工作区、owner、Profile、当前阶段、处理器、重试次数、状态、耗时、
是否使用模型、是否降级和脱敏错误。它记录一次理解 attempt 的运行信息，
不承担任务队列职责。

### 3.4 `file_chunks`

继续复用现有分块表，没有建立第二套不兼容系统。增量增加：

- `page_number` 可空；
- `source_type`；
- `section_path`；
- `char_start`、`char_end`；
- `chunk_hash`；
- `parser_version`。

PDF 继续使用已有页码分块逻辑；Markdown 使用相同表，页码为空并保留标题路径。

## 4. 各文件类型

### CSV

- 尝试 UTF-8-SIG、UTF-8、GB18030；
- 检测常见分隔符；
- 分块统计总行数和缺失值；
- 样本推断字段类型、样本值、数值统计、日期范围和候选 ID；
- 记录重复行、空表、高缺失比例和编码降级。

### XLSX

- 使用 openpyxl 读取工作簿元数据；
- 使用 Pandas 逐个读取所有工作表的受限样本；
- 返回工作表名、可见性、行列数、字段、类型、样本、缺失、重复、数值统计、
  日期范围和候选 ID；
- 不执行宏，不请求外部链接，不把整张表写入 Profile。

没有加入未验证的 `.xls` 支持。

### PDF

- 使用 PyMuPDF 提取页数、元数据、每页文本长度、标题候选和文本长度；
- 判断疑似扫描页比例；
- 复用 `index_pdf_file` 和 `file_chunks`；
- 保留页码和 chunk 引用能力；
- 无文本时产生 `PDF_OCR_REQUIRED`，Profile 仍可 `ready`，并标记降级；
- 摘要只来自已提取文本，不虚构文档内容。

### 图片

- Pillow 校验格式、宽高、像素数和颜色模式；
- 复用现有 Tesseract OCR 服务；
- 保存 OCR 状态、引擎、文本长度和受限摘要；
- 规则判断截图、扫描件、表格图或普通图片；
- OCR 不可用时保留基础 Profile，并产生 `OCR_UNAVAILABLE`；
- OCR 成功仍产生人工核对提示，不把识别文本视为绝对准确。

### Markdown

- 支持 `.md` 和 `.markdown`；
- 提取标题和层级路径、代码块、表格、链接、文本长度和 chunks；
- 不执行 HTML、JavaScript、命令或代码块；
- 不跟随本地文件引用；
- 不请求外部 URL；
- 前端只用 React 文本节点展示结构和摘要，没有使用
  `dangerouslySetInnerHTML`。

## 5. 角色与标签

内置角色：

```text
primary_dataset
supplementary_dataset
rule_document
reference_document
resume
job_description
research_material
image_evidence
report_template
supporting_material
unknown
custom
```

规则/DeepSeek 只写 `suggested_role`。用户确认写入
`workspace_files.user_confirmed_role`，Workspace Context 始终优先使用确认值。
自定义角色保存为 `custom:<文本>`，只允许中英文、数字、空格和有限分隔符，
长度最多 60。

系统标签保存在 Profile，用户标签保存在 `workspace_files.tags_json`。
标签忽略大小写去重，用户最多 20 个、每个最多 30 字符，控制字符和尖括号内容
会被过滤。角色和标签修改写入 `audit_logs`。

## 6. 关系发现

入口：

```python
discover_file_relations(
    db,
    workspace_id=workspace_id,
    owner_user_id=user_id,
    file_ids=None,
    use_deepseek=False,
)
```

确定性规则：

- 表格列集合 Jaccard 相似度；
- 文件名时间、版本、地区和岗位差异；
- PDF/Markdown 摘要、标题与表格字段重合；
- 图片 OCR 摘要与文档标题、摘要或表格字段重合。

候选证据只保存列名、相似度、文件名信号、命中字段或 Token 重合等短信息，
不保存整份原文。默认最小保存阈值为 `0.60`，高置信展示阈值为 `0.80`。
这些数值是 UI/规则阈值，不是真实概率。

可选 DeepSeek 只接收裁剪后的摘要、角色、列名和确定性证据，输出必须通过严格
Pydantic Schema。非法 JSON、超时或无 Key 时保留确定性候选。默认每次关系发现
最多评估 100 对文件、最多 5 次模型增强；自动结果始终为 `suggested`。

## 7. Workspace Context

入口：

```python
build_workspace_context(
    db,
    workspace_id=workspace_id,
    owner_user_id=user_id,
    selected_file_ids=None,
)
```

响应 `context_version` 为 `2.03`，包含：

```json
{
  "context_version": "2.03",
  "workspace": {},
  "user_goal": null,
  "selected_file_ids": [],
  "files": [],
  "confirmed_relations": [],
  "pending_high_confidence_relations": [],
  "data_quality_issues": [],
  "available_tools": [],
  "unready_files": [],
  "limits": {}
}
```

默认不包含完整文件原文、OCR 全文、绝对路径、密码、Token、Session 或 API Key。
文件结构被压缩为后续 Agent 所需字段。默认最多 20 个文件和 30000 个序列化字符；
用户确认角色优先、ready 文件优先，超过限制时先裁剪统计和结构，再省略低优先级
文件，并在 `limits.omitted_file_ids` 中说明。

本阶段只提供 Context，不启动 Supervisor。

## 8. V2 API

文件理解：

```text
POST  /api/v2/workspaces/{workspace_id}/files/{file_id}/understand
POST  /api/v2/workspaces/{workspace_id}/files/understand
GET   /api/v2/workspaces/{workspace_id}/files/{file_id}/profile
GET   /api/v2/workspaces/{workspace_id}/files/{file_id}/profile/versions
PATCH /api/v2/workspaces/{workspace_id}/files/{file_id}/profile
```

关系：

```text
POST  /api/v2/workspaces/{workspace_id}/file-relations/discover
GET   /api/v2/workspaces/{workspace_id}/file-relations
PATCH /api/v2/workspaces/{workspace_id}/file-relations/{relation_id}
```

上下文：

```text
POST /api/v2/workspaces/{workspace_id}/context-preview
```

上传：

```text
POST /api/v2/workspaces/{workspace_id}/files
POST /api/v2/workspaces/{workspace_id}/files/batch
```

所有修改请求继续使用 Session Cookie + CSRF Header。Profile PATCH 只能修改确认角色
和用户标签；客户端不能修改结构统计、置信度、模型信息或服务器路径。

## 9. 上传安全和配额

默认值：

| 配置 | 默认值 |
| --- | ---: |
| `UPLOAD_MAX_FILE_SIZE_BYTES` | 20971520（20 MiB） |
| `UPLOAD_MAX_BATCH_FILES` | 10 |
| `WORKSPACE_MAX_FILES` | 50 |
| `USER_STORAGE_QUOTA_BYTES` | 209715200（200 MiB） |
| `PDF_MAX_PAGES` | 200 |
| `IMAGE_MAX_PIXELS` | 20000000 |

服务端校验扩展名、声明 MIME、文件头和内容可读性。XLSX 检查 ZIP 结构、必要条目、
解压大小和压缩比；PDF 检查头、可打开性和页数；图片检查文件头、Pillow 可读性和
像素数；CSV/Markdown 检查文本编码和二进制空字符。保存名为 UUID，不使用用户
路径，不覆盖已有文件。

错误语义：

- `413`：单文件或批量数量超过安全上限；
- `415`：扩展名或 MIME 不支持/不匹配；
- `422`：文件头、压缩结构、图片、PDF 或文本内容无效；
- `429`：工作区数量或普通用户存储配额不足。

管理员不受普通工作区数量和用户存储配额限制，但仍受单文件大小、批量数量、
PDF 页数、图片像素和内容安全校验约束。

## 10. 前端

工作区详情页新增：

- 多文件选择和拖拽上传；
- 文件名、MIME、大小、上传状态和逐文件错误；
- 单文件、批量和重新理解；
- 摘要、结构、角色、标签、质量、解析器、DeepSeek/降级和置信度；
- 推荐角色确认、自定义角色和用户标签；
- 关系候选、证据、状态、确认、拒绝、修改和备注；
- Context 文件、角色、已确认关系、高置信待确认关系、质量问题、未就绪文件和裁剪提示。

页面不显示服务器路径，不保存完整原文，不渲染不受信任 HTML。

## 11. 测试

自动化测试覆盖：

- 迁移从零升级、回退到 `20260723_0003` 和再次升级；
- 支持类型、MIME、文件头、大小、批量、配额和路径净化；
- CSV、多 Sheet XLSX、PDF、扫描 PDF、图片 OCR、Markdown；
- DeepSeek 关闭和非法 JSON 降级；
- Profile 版本和确认角色保护；
- 表格、规则文档、图片 OCR 关系、低置信过滤、去重和用户修正；
- 跨用户/工作区隔离；
- Workspace Context 的选择、角色优先、关系、脱敏和裁剪；
- V2-02 认证和工作区回归；
- 现有 OCR、RAG、分析、报告和多文件模块导入。

测试不读取真实 `.env`，不调用真实 DeepSeek，不修改真实 `app.db`。

## 12. 数据库升级与回滚

先停止写入并备份真实数据库，再检查：

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\alembic.exe -c alembic.ini current
.\.venv\Scripts\alembic.exe -c alembic.ini heads
```

确认当前为 `20260723_0003` 后：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c alembic.ini current
```

只回退 V2-03：

```powershell
.\.venv\Scripts\alembic.exe -c alembic.ini downgrade 20260723_0003
```

回退会删除 V2-03 Profile、关系、处理运行记录和新增 chunk 定位字段。产生真实数据后
必须先备份和评估，不能通过删除 `app.db` 回滚。

## 13. 当前限制和下一阶段

- 当前理解仍在同步 HTTP 请求内执行；
- OCR 质量依赖 Tesseract 和语言包；
- PDF 扫描件只提示需要 OCR，没有实现 PDF 页图 OCR；
- CSV 日期范围和数值统计主要基于受限样本；
- 关系是可解释启发式候选，不是真实概率或事实；
- 未实现持久化语义向量库；
- UI 是稳定操作流程，不是最终视觉稿。

下一阶段入口是 V2-04：计划草稿与确认、持久化队列、SSE、取消和受限局部重试。
Supervisor 和专业子 Agent 应在可靠异步执行层之后实施。
