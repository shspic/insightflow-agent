# InsightFlow V3 分阶段 Codex 执行提示词

配套规划：[V3 工程审查路线](V3_ENGINEERING_REVIEW_ROADMAP.md)

## 使用方法

1. 严格按阶段 0 → 6 顺序执行。
2. 每次只把一个阶段提示词交给 Codex，不要一次要求完成全部阶段。
3. 上一阶段必须通过验收并由你确认后，才进入下一阶段。
4. 每个新任务都从项目根目录 `D:\spir\NO2_agent` 开始。
5. 不要让 Codex自动提交、推送或部署，除非你在当次任务中明确授权。
6. 当前已知存在用户未提交改动：`backend/tests/test_v2_task_execution.py`。每个阶段都必须保留它，除非你明确说明该改动已经提交或允许调整。

---

## 通用执行约束

下面这段已经写进每个阶段的提示词核心要求中。如果你另开任务，仍建议保留。

```text
你正在修改 D:\spir\NO2_agent。先完整阅读根目录 AGENTS.md，并严格遵守其中的中文、最小修改、删除安全和验证规则。

开始前必须：
1. 执行 git status --short，记录并保护所有已有未提交改动；
2. 阅读本阶段指定文件及其附近调用关系；
3. 用简短计划说明目标、关键假设和每一步验证方式；
4. 不修改本阶段以外的功能，不顺手重构，不自动提交或推送；
5. 不覆盖 backend/tests/test_v2_task_execution.py 的用户改动；如任务确实与其冲突，停止并说明。

实现时：
- 只使用预设安全工具，不执行用户输入的任意 Python、Shell、SQL 或 URL；
- 新增数据库字段必须提供 Alembic 迁移和迁移测试；
- 新增 API 必须更新接口说明；
- 模型输出必须经过 Pydantic 校验；
- 所有专业结论必须使用“辅助审查、风险提示、证据定位、人工复核”，禁止宣称自动合规判定；
- 不提交密钥、真实商业资料、模型缓存、向量索引和生成的运行时数据库。

结束前必须：
1. 检查 git diff，确认每一项改动都服务于本阶段；
2. 运行最小相关测试，再运行本阶段要求的完整验证；
3. 明确列出实际通过、失败和未验证内容；
4. 按 AGENTS.md 的“已完成”格式汇报；
5. 未实际运行的验证不得写成通过。
```

---

# 阶段 0：事实基线、TF-IDF 命名和旧版冻结

## 交给 Codex 的提示词

```text
请执行 InsightFlow V3 阶段 0：事实基线、TF-IDF 命名修正和 V2 通用主线冻结。

项目路径：D:\spir\NO2_agent
规划真源：docs/V3_ENGINEERING_REVIEW_ROADMAP.md

先完整阅读：
- AGENTS.md
- README.md
- docs/EVALUATION.md
- docs/V2_05_EVALUATION_GUIDE.md
- docs/MCP_PLAN.md
- backend/app/services/vector_service.py
- backend/app/services/rag_service.py
- backend/app/evaluation/dataset.py
- backend/app/evaluation/runner.py
- backend/app/core/config.py
- backend/.env.example
- 相关 RAG 测试

开始前执行 git status --short。保护所有用户未提交改动，特别是 backend/tests/test_v2_task_execution.py。

目标：
1. 建立一份基于源码的 V3 基线审计，清楚区分已有能力、名义存在但未实现的能力、确定性自检和真实 AI 评测。
2. 修正 TF-IDF 被标记为 vector 的问题。
3. 将 V2 通用文档分析明确标记为 general 冻结基线，但本阶段不改产品路由和数据库。
4. 修正 README、配置和文档中超出源码能力或已经过期的表述。

实现要求：
- 新增 docs/V3_BASELINE_AUDIT.md，至少记录：当前 Agent 实际结构、RAG 实际算法、85 条评测实际含义、MCP 当前状态、DeepSeek 当前配置状态、可复用基础设施和 V3 缺口。
- API 和内部检索模式使用 tfidf、keyword、auto；不得继续把 TF-IDF 结果返回为 vector。
- 如需兼容旧调用，可把请求参数 vector 映射为 tfidf，并在响应或日志中明确 deprecated；不要维持两个行为不同的实现。
- 默认配置从 RAG_RETRIEVAL_MODE=auto 或 tfidf 中选择与实际行为一致的值；不要声称 Chroma 已实现，除非源码和依赖确实存在。
- README 中的功能、限制、评测和 DeepSeek 模型名必须与当前源码和实际官方配置一致。模型名从环境变量读取，不把未经调用验证的模型写成“已验收”。
- 保留 V2 deterministic 数据和测试作为 general 回归，不删除。
- 不实现 V3 数据模型、界面分区、Embedding、MCP 或新 Agent。

测试要求：
- 为 tfidf、keyword、auto 和 vector 兼容映射增加或调整最小测试；
- 运行相关 RAG 测试；
- 运行 backend 全量 pytest；
- 若前端或 README 未影响前端代码，不需要无意义修改前端。

验收标准：
- 搜索源码和文档后，除明确的弃用兼容说明外，不再把 TF-IDF 称为 vector；
- docs/V3_BASELINE_AUDIT.md 的每项结论能指向源码或实际测试；
- README 明确说明 85 条 deterministic 通过不等于真实模型准确率；
- 不覆盖既有未提交改动；
- 实际运行的后端测试通过。
```

---

# 阶段 1：engineering / general 分区与逐字输入缺陷

## 交给 Codex 的提示词

```text
请执行 InsightFlow V3 阶段 1：产品分区、工程项目入口和创建表单逐字输入缺陷修复。

项目路径：D:\spir\NO2_agent
规划真源：docs/V3_ENGINEERING_REVIEW_ROADMAP.md
前置条件：阶段 0 已验收。

先完整阅读：
- AGENTS.md
- docs/V3_ENGINEERING_REVIEW_ROADMAP.md
- docs/V3_BASELINE_AUDIT.md
- frontend/src/App.jsx
- frontend/src/components/AppLayout.jsx
- frontend/src/pages/WorkspaceList.jsx
- frontend/src/pages/WorkspaceDetail.jsx
- frontend/src/components/common/index.jsx 中 Dialog、Input、Textarea
- frontend/src/utils/ui.js 及测试
- frontend/src/App.css 与 styles/tokens.css
- backend/app/models/workspace.py
- backend/app/schemas/workspace.py
- backend/app/services/workspace_service.py
- backend/app/api/v2/workspaces.py
- 现有 Alembic 迁移和 workspace 测试

开始前执行 git status --short，保护所有已有改动。

目标：
1. 将产品入口拆为 engineering 和 general。
2. 旧工作区全部归入 general；新工程入口创建的数据为 engineering。
3. 工程审查成为默认首页，general 只承接旧功能。
4. 修复名称和描述输入时只能逐字输入、焦点或中文输入法组合被打断的问题。
5. 保留现有视觉系统，不做无关重设计。

数据实现：
- 在 workspaces 增加 workspace_type，允许值仅为 engineering、general。
- Alembic 迁移必须把已有记录填充为 general，并提供非空约束、索引或检查约束。
- WorkspaceCreate、WorkspaceResponse、列表查询和服务层必须支持类型。
- API 列表支持按 workspace_type 过滤；服务端验证类型，不信任前端。
- 旧 API 创建调用默认 general，工程入口显式创建 engineering，避免破坏旧 general 行为。

前端信息架构：
- 工作品牌暂用“InsightFlow 工程投标审查 Agent”；副标题使用“工程检测服务投标资料辅助审查”。
- 主导航顺序：工程审查、通用分析（旧版）、使用量、管理后台。
- 工程审查默认路由：/engineering/projects。
- general 路由：/general/workspaces。
- /usage 与 /admin 保持工具属性。
- 根路由跳转到 /engineering/projects。
- 旧 /workspaces 路由做明确兼容跳转，不删除旧接口。
- 工程区域使用“审查项目”“新建审查项目”；general 继续使用“工作区”。
- 尽量复用现有列表和详情组件，通过明确参数或小型包装区分文案和路由，不复制两套大组件。

输入缺陷要求：
- 先复现并记录：英文连续输入、中文输入法组合输入、名称和描述两个控件。
- 重点检查 Dialog 的 useEffect 是否因内联 onClose 每次渲染变化而反复清理和聚焦。
- 做最小根因修复。不要用非受控表单重写来掩盖问题。
- 弹窗打开时仍应正确聚焦，Escape 关闭、Tab 焦点陷阱和关闭后恢复焦点不能退化。

测试与验证：
- Alembic 从当前 head 升级到新 head；验证旧工作区迁移为 general。
- 后端 workspace API 测试覆盖类型创建、筛选、非法类型和用户隔离。
- 前端现有 npm test、npm run build。
- 使用 Playwright 或当前可用浏览器自动化，实际输入完整中文项目名和多句描述，证明不会逐字失焦；同时验证键盘 Tab 和 Escape。
- 不为这一个缺陷引入大型前端测试框架；优先使用现有测试与浏览器 E2E。

本阶段不要实现：
- 审查规则、风险项、Embedding、MCP、新 Agent；
- 删除 general 功能；
- 无关页面视觉重构。

验收标准：
- 旧数据只出现在 general；engineering 和 general 查询互不混淆；
- 新工程项目创建成功并进入工程路由；
- 连续中英文输入不丢字、不跳焦点；
- 根路由默认进入工程审查；
- 后端测试、前端测试和构建实际通过。
```

---

# 阶段 2：工程审查数据模型、规则引擎和合成材料

## 交给 Codex 的提示词

```text
请执行 InsightFlow V3 阶段 2：工程投标审查数据基础、确定性规则引擎和合成演示材料。

项目路径：D:\spir\NO2_agent
规划真源：docs/V3_ENGINEERING_REVIEW_ROADMAP.md
前置条件：阶段 1 已验收。

先完整阅读：
- AGENTS.md
- docs/V3_ENGINEERING_REVIEW_ROADMAP.md
- backend/app/models 下 workspace、file_profile、file_relation、task、tool_call
- backend/app/schemas 下 workspace、file_understanding、file_relation、task_execution
- backend/app/services/file_understanding_service.py
- backend/app/services/file_relation_service.py
- backend/app/services/parser_service.py
- backend/app/services/analysis_service.py
- backend/app/db/base.py 和 Alembic 当前 head
- examples/demo_workspace

开始前执行 git status --short，保护已有改动。

目标：
1. 为工程检测服务投标资料一致性辅助审查建立最小、可追溯的数据模型。
2. 创建版本化 YAML 规则库和确定性规则执行器。
3. 创建一套完全合成、带标准答案的黄金演示材料。
4. 在不调用 LLM 的情况下发现预置的字段缺失、跨文件不一致、日期和数值问题。

文件角色仅实现：
- tender_requirement
- bid_response
- personnel_equipment_data
- qualification_attachment
- clarification_document
- supplementary_attachment

关系类型仅实现：
- constrains
- responds_to
- data_source_of
- evidence_for
- supersedes

用户确认仍是事实真源。系统建议的角色和关系不能自动变成已确认事实。

新增最小实体：
- ReviewRun：审查运行、状态、规则包版本与哈希、模型/Prompt/检索快照占位；
- Evidence：文件定位、引用文本、内容哈希、解析器版本；
- ReviewFinding：问题、风险、结论、建议、rule_id、rule_version、evidence_ids、状态和来源步骤；
- ReviewAction：人工确认、驳回、修改、解决的追加式审计记录。

不要把所有内容塞进一个 JSON 大字段；也不要为首版拆出十几个表。evidence_ids 可以在首版使用经过校验的 JSON 列表，但 Evidence 必须是独立实体。

规则库：
- 放在 backend/app/review_rules/ 或当前结构下更一致的位置；
- 使用 YAML 作为版本控制真源；
- 加载后必须用 Pydantic 校验；
- 首版规则类型只有 required_field、cross_file_equal、numeric_threshold、date_order、document_presence、evidence_required；
- 每条规则包含 rule_id、version、title、description、severity、inputs、parameters、source_kind 和 source_locator；
- 规则执行只接受结构化字段和受控 evidence_id，不执行表达式、Python、SQL 或模板代码。

合成材料：
- 新建 examples/engineering_review_v1/golden_case；
- 生成合成招标要求 PDF、投标响应 PDF、人员设备 Excel、合成资质附件 PDF、项目澄清 Markdown；
- 所有页面显著标注“合成演示数据”；
- 人名、单位、编号、地址全部虚构，不能复制真实公告里的个人或企业信息；
- 规则内容可以参考公开招投标材料结构，但不得提交受版权保护的完整国家标准；
- 同时创建 ground_truth.json，记录文件角色、字段值、预期问题、规则和精确证据定位；
- 至少注入 10 个问题，覆盖缺失、不一致、日期、阈值、版本提示和证据不足；
- “标准版本可能过期”只能输出待复核风险，不能输出不合规结论。

如果当前环境提供 PDF 和 Spreadsheets skill，必须按对应 SKILL.md 创建并渲染检查 PDF/XLSX。生成后的 PDF 逐页检查，Excel 检查工作表、公式、格式和实际值。不要把用于生成材料的临时代码作为项目亮点。

服务与 API：
- 实现规则加载、结构化字段归一化、Evidence 创建和确定性检查 service；
- 提供最小内部或受权 API 用于对 engineering workspace 创建 ReviewRun 并读取结果；
- general workspace 调用工程审查接口必须被拒绝；
- 所有查询继续执行 owner_user_id 与 workspace_id 隔离。

测试：
- Alembic 升级与完整降级边界按项目现有策略验证；
- YAML 合法、非法、重复 rule_id 测试；
- 六类规则各有正例和反例；
- 黄金案例实际运行并与 ground_truth 对比；
- Evidence locator 和 content_hash 测试；
- 用户隔离、general 拒绝和人工动作追加测试；
- 运行 backend 全量 pytest。

本阶段不要实现：
- 工程审查完整前端；
- Embedding、混合检索、MCP；
- DeepSeek 自动抽取；
- PostgreSQL、Redis、Celery。

验收标准：
- 黄金案例在 LLM_ENABLED=false 下稳定输出预期确定性问题；
- 每条正式问题都有 rule_id 和真实存在的 evidence_id；
- 合成材料经过视觉与数据检查；
- general 完全不受工程规则影响；
- 后端全量测试实际通过。
```

---

# 阶段 3：工程审查端到端 MVP 与人工复核

## 交给 Codex 的提示词

```text
请执行 InsightFlow V3 阶段 3：工程投标资料辅助审查端到端 MVP。

项目路径：D:\spir\NO2_agent
规划真源：docs/V3_ENGINEERING_REVIEW_ROADMAP.md
前置条件：阶段 2 已验收，黄金合成材料和确定性规则已可运行。

先完整阅读：
- AGENTS.md
- docs/V3_ENGINEERING_REVIEW_ROADMAP.md
- 阶段 2 新增的 ReviewRun、Evidence、ReviewFinding、ReviewAction 和规则服务
- frontend/src/pages/WorkspaceDetail.jsx
- frontend/src/components/WorkspaceUnderstanding.jsx
- frontend/src/components/TaskExecutionFlow.jsx
- frontend/src/components/ReportCenter.jsx
- frontend/src/components/AgentTrace.jsx
- frontend/src/api 下 workspace、fileUnderstanding、workspaceTasks、reports
- backend/app/services/report_version_service.py
- 相关 API 和测试

开始前执行 git status --short，保护已有改动。

用户目标：
从创建工程项目开始，上传合成资料，确认文件角色，启动审查，查看问题与证据，人工确认/驳回/修改，最后导出审查报告。

实现范围：
1. 工程项目详情页分区：项目资料、审查任务、风险问题、人工复核、审查报告。
2. 文件上传后展示建议角色并要求用户确认；未确认关键角色时禁止正式审查。
3. 审查前展示计划、使用规则包版本、文件范围和已知缺失信息。
4. 风险问题列表支持严重级别、分类、复核状态筛选。
5. 点击问题可以看到规则、报告内容、PDF 页码或 Excel 单元格、引用片段、证据哈希摘要和处理建议。
6. 人工可以确认、驳回或修改问题；修改必须保留原始结论和追加式动作记录。
7. 报告导出包含问题清单、风险等级、证据、规则、建议、复核状态、未解决项和限制声明。
8. 页面固定显示“辅助审查，不替代专业人员判断”。

交互原则：
- engineering 使用“项目”和“审查”，general 保持旧“工作区”和“分析”文案；
- 不复制整个 WorkspaceDetail；提取真正共享的小组件或通过区域配置复用；
- Evidence 不只显示一段文本，必须显示可定位的页码、工作表与单元格等；
- 信息不足时显示“需要补充材料”而不是生成确定结论；
- 不把置信度小数伪装成专业风险概率。

API：
- 补齐 ReviewRun 创建、详情、问题列表、问题详情、人工动作和报告接口；
- 状态变化必须校验合法转换；
- 重复提交人工动作要有明确幂等策略；
- 继续执行用户、workspace_type 和资源归属校验。

测试与验证：
- 后端 API 测试覆盖完整状态流、非法状态、越权和幂等；
- 前端 npm test、npm run build；
- 使用 Playwright 实际跑通黄金项目：创建工程项目 → 上传 → 角色确认 → 审查 → 查看证据 → 确认/驳回/修改 → 导出；
- 检查桌面与至少一个移动视口；
- 检查键盘焦点、对话框、错误提示和空状态；
- 下载并打开最终 PDF/DOCX/Markdown 报告，核对内容与问题状态。

本阶段不要实现：
- Embedding、混合检索、MCP；
- 新增专业工程规则；
- general 页面重构；
- 公网部署。

验收标准：
- 黄金案例端到端可演示；
- 所有正式问题都能跳到规则和证据；
- 人工动作可追溯；
- 报告不声称自动合规；
- 后端测试、前端测试、构建和关键 E2E 实际通过。
```

---

# 阶段 4：Embedding、混合检索与真实检索评测

## 交给 Codex 的提示词

```text
请执行 InsightFlow V3 阶段 4：真实 Embedding、混合检索和可复现检索评测。

项目路径：D:\spir\NO2_agent
规划真源：docs/V3_ENGINEERING_REVIEW_ROADMAP.md
前置条件：阶段 3 已验收。

先完整阅读：
- AGENTS.md
- docs/V3_ENGINEERING_REVIEW_ROADMAP.md
- 当前 rag、tfidf、file_chunk、parser、Evidence 和 ReviewRun 实现
- backend/app/evaluation 全部代码
- 当前 requirements、Dockerfile、配置和测试
- BGE-M3 与 FlagEmbedding 官方模型说明

开始前执行 git status --short，保护已有改动。

目标：
1. 建立真实 dense embedding 索引。
2. 实现 BM25 + dense 的混合检索和结果去重。
3. 用独立查询集对比 TF-IDF、BM25、dense、hybrid 和可选 rerank。
4. 输出真实 Recall@3、Recall@5、MRR、引用正确率和 P95 延迟。

依赖约束：
- 本阶段允许为真实检索增加必要依赖，但必须先说明选择和部署成本；
- 优先使用 BAAI/bge-m3 作为初始中文语义模型；
- 持久化向量索引可以使用 Chroma，但项目亮点必须是混合检索、证据定位和评测，不是“接入 Chroma”；
- 新依赖写入 requirements 并验证 Docker 构建影响；
- 模型缓存和索引文件不得提交 Git。

检索实现：
- 支持 tfidf、bm25、dense、hybrid、hybrid_rerank；
- BM25 对条款号、证书号、人名和精确字段提供词法召回；
- dense 使用真实模型生成向量，不允许用 TF-IDF 数组冒充 embedding；
- hybrid 使用可解释的 Reciprocal Rank Fusion 或同等简单融合，并记录融合参数；
- 候选以 workspace_id、file_id、locator 和内容哈希隔离、去重；
- 每个结果返回 retrieval_mode、原始排名、融合分数、文件、页码/单元格、chunk_id 和 content_hash；
- 索引具备模型名、维度、chunk 策略和索引版本；配置变化时不得静默复用不兼容索引；
- general 旧 RAG 可以继续使用兼容路径，不强行迁移所有旧数据。

reranker：
- `bge-reranker-v2-m3` 只作为可选实验；
- 只有 MRR 或引用正确率有可重复收益且 P95 延迟可接受时才进入默认链路；
- 没有收益就记录实验结果并关闭，不为了技术名词保留。

评测集：
- 在 examples/engineering_review_v1/evaluation 下创建 30～50 条查询；
- 每条包含 query_id、query、relevant_evidence_ids、split、category；
- 至少覆盖精确编号、同义表达、跨文件约束、否定条件、澄清文件覆盖旧要求和无答案；
- development 与 test 分离；最终 test 只在参数冻结后运行；
- 无答案查询单独统计，不能通过返回无关结果获得分数。

评测运行器：
- 从真实索引和检索结果计算指标；
- 生成 JSON 和 Markdown 对比报告；
- 导出失败查询、召回片段和排名；
- 记录模型、规则、chunk、top_k、融合参数、机器环境和运行时间；
- 不把预期答案直接复制为实际结果。

测试与验证：
- 单元测试：BM25、dense 接口、RRF、去重、索引版本、租户隔离；
- 集成测试：构建黄金案例索引并检索；
- 真实运行 development 和冻结后的 test 评测；
- 记录内存、索引耗时、查询 P95；
- backend 全量 pytest；
- 验证 Docker 镜像或至少说明未验证原因。

验收标准：
- dense 确实来自真实 embedding 模型；
- 对比报告包含实际指标和失败样例；
- hybrid 的收益与成本可解释；若没有优于基线，也必须诚实记录；
- 引用 locator 能回到原始合成文件；
- README 只写实际获得的指标。
```

---

# 阶段 5：可信 Agent、MCP 工具调用与局部重试

## 交给 Codex 的提示词

```text
请执行 InsightFlow V3 阶段 5：可信工程审查 Agent、真实 MCP 工具调用和失败步骤局部重试。

项目路径：D:\spir\NO2_agent
规划真源：docs/V3_ENGINEERING_REVIEW_ROADMAP.md
前置条件：阶段 4 已验收，混合检索和评测可运行。

先完整阅读：
- AGENTS.md
- docs/V3_ENGINEERING_REVIEW_ROADMAP.md
- docs/MCP_PLAN.md
- backend/app/agents 全部 V2 相关实现
- backend/app/workers/task_worker.py
- backend/app/services/task_planning_service.py、task_queue_service.py、llm_service.py
- backend/app/models/task_step.py、tool_call.py、agent_run.py、prompt_version.py
- 阶段 2～4 的 ReviewRun、Evidence、ReviewFinding、规则与检索服务
- docker-compose.yml、backend/Dockerfile、requirements.txt

同时核对当前官方文档：
- MCP Python SDK 2.x 和 2026-07-28 协议；
- DeepSeek 当前可用模型、JSON Output 和 tool calling；
不要照抄旧 FastMCP 或已停用模型名示例。

开始前执行 git status --short，保护已有改动。

目标架构：
- Supervisor：选择检查、追问、重试或结束；
- Extraction：抽取字段和 Evidence；
- Verification：混合检索、MCP 规则工具、确定性校验；
- Reporting：生成结构化问题清单和审查报告；
- Quality Review：确定性质量门，不包装成额外专业 Agent。

general 旧五 Agent 工作流保留为冻结兼容路径。不要直接删除，engineering 使用独立 V3 graph 或明确分支，避免一次性重写 general。

MCP 实现：
- 使用官方 Python SDK 稳定版并锁定经验证版本；截至规划日期为 mcp==2.0.0；
- 使用 v2 的 MCPServer，不使用旧 FastMCP 导入；
- 新增独立 Review Tools MCP Server；
- 首版仅暴露 search_review_rules 和 run_bid_consistency_checks；
- 使用 Streamable HTTP；本地绑定 127.0.0.1，容器网络使用服务名；
- engineering Verification 通过 MCP Client 执行 tools discovery 和 call_tool；
- MCP 输入只允许 workspace_id、review_run_id、rule_pack_id、受控字段和 evidence_id；
- 服务端重新校验用户/工作区归属，不能接受任意文件路径、Python、Shell、SQL、URL 或动态 import；
- 记录 server、tool_name、schema_version、request_id、输入摘要、输出摘要、latency_ms、status 和 error_code；
- 工程模式不得静默回退到同名本地函数，否则无法证明 MCP 真调用。

DeepSeek：
- 模型名只从配置读取；根据官方当前状态支持 deepseek-v4-pro 或 deepseek-v4-flash；
- 使用 JSON Output 或严格 tool schema 生成结构化结果；
- 所有模型输出和工具参数再经过 Pydantic 校验；
- 模型不得直接生成数字校验结果；数字、日期和一致性由工具返回；
- 信息不足时输出结构化 clarification，不允许编造字段；
- 记录 model_name、prompt_version、token usage、latency 和失败原因；
- LLM 关闭时保留可演示的确定性路径，但真实模型评测必须单独运行并标识。

质量门：
- 每个 finding 必须有 rule_id、rule_version 和至少一个有效 evidence_id；
- evidence 必须属于当前 workspace，content_hash 与当前解析结果一致；
- 数字结论必须引用工具调用输出；
- 证据不足时将候选降级为 need_more_information，不进入正式问题清单；
- Quality Review 返回结构化失败类型和 retry_step_id。

局部重试：
- 只允许对 retryable 错误重试；
- 至少区分 MCP_UNAVAILABLE、MODEL_OUTPUT_INVALID、EVIDENCE_STALE、RULE_INPUT_MISSING、PERMANENT_VALIDATION_ERROR；
- MCP_UNAVAILABLE、MODEL_OUTPUT_INVALID 可以按上限重试当前步骤；
- EVIDENCE_STALE 指定重新抽取相关文件，不重跑无关文件；
- 永久校验错误停止并请求人工处理；
- 重试必须复用已成功且版本仍有效的结果；
- 记录 plan_version、step_id、attempt、原因和复用结果。

故障注入测试：
1. MCP 第一次超时、第二次成功：只重试 Verification；
2. MCP 永久不可用：达到上限后停止并展示人工处理状态；
3. DeepSeek 返回空 JSON：结构化重试，不入库错误 finding；
4. 伪造 evidence_id：质量门阻断；
5. 数字结论不是工具输出：质量门阻断；
6. 规则输入缺失：触发追问，不强行结论。

验证：
- MCP tools/list 与 tools/call 真实成功；
- MCP Inspector 或官方客户端可以独立发现两个工具；
- LangGraph/Worker 真实调用 MCP，不能用 mock 作为唯一验收；
- 注入故障后检查 AgentTrace、ToolCall、TaskEvent 和 ReviewRun；
- 后端全量 pytest；
- 前端测试和构建；
- docker compose 启动 backend、worker、mcp 和 frontend，并完成黄金案例。

验收标准：
- MCP 调用在轨迹中可验证；
- 暂时故障只重试指定步骤；
- 无证据结论率为 0；
- 三个核心节点职责不重叠；
- general 旧链路仍可回归；
- 所有实际验证结果如实记录。
```

---

# 阶段 6：真实评测、E2E、公网部署和求职材料

## 交给 Codex 的提示词

```text
请执行 InsightFlow V3 阶段 6：完整真实评测、关键 E2E、部署收口和求职材料更新。

项目路径：D:\spir\NO2_agent
规划真源：docs/V3_ENGINEERING_REVIEW_ROADMAP.md
前置条件：阶段 5 已验收，MCP 和可信 Agent 已能完成黄金案例。

先完整阅读：
- AGENTS.md
- docs/V3_ENGINEERING_REVIEW_ROADMAP.md
- backend/app/evaluation 全部代码和 engineering-review-v1 数据
- 所有 ReviewRun、AgentTrace、ToolCall、报告与人工复核实现
- .github/workflows/ci.yml
- docker-compose.yml、docker-compose.prod.yml、render.yaml
- docs/DEPLOYMENT.md、DEMO_SCRIPT.md、RESUME.md、INTERVIEW_QA.md、TESTING.md
- README.md、CHANGELOG.md、VERSION

开始前执行 git status --short，保护已有改动。

目标：
1. 冻结 engineering-review-v1 测试集并运行真实评测。
2. 建立可重复的端到端演示与故障路径测试。
3. 让 backend、worker、MCP 和 frontend 可按生产配置部署。
4. 用实际数据更新 README、简历和面试材料。

评测：
- 明确 development、validation、test 划分和版本哈希；
- 真实运行检索、字段抽取、问题识别、引用、质量门和局部重试评测；
- 指标至少包含 Recall@3、Recall@5、MRR、引用正确率、字段 F1、问题 F1、无证据结论率、质量门拦截率、局部重试成功率、平均/P95 延迟、模型和工具调用数；
- 生成机器可读 JSON 与人类可读 Markdown；
- 导出失败案例，不只展示平均分；
- 记录 DeepSeek 模型名、Embedding 模型、Prompt 版本、规则版本、代码版本和运行环境；
- V2 85 条 deterministic 只作为 general 回归，报告中与 V3 效果评测分开。

E2E：
- 使用 Playwright skill 或项目认可的浏览器自动化方式；
- 覆盖登录、创建工程项目、上传黄金材料、确认角色、启动审查、查看证据、人工确认/驳回/修改、导出报告；
- 覆盖 MCP 暂时故障和恢复；
- 覆盖逐字输入缺陷回归；
- 覆盖第二个用户无法访问第一个用户项目；
- 桌面和移动视口各保留关键截图；
- 不把截图存在临时目录后声称已经交付。

CI：
- 后端单元与集成测试；
- 前端 npm test 和 build；
- Alembic 完整升级；
- 小型、无外部 API 的 engineering smoke evaluation；
- 真实 DeepSeek 和完整 Embedding 评测不在每次 PR 强制运行，但提供显式命令和预算说明；
- CI 不下载不可控的大模型缓存，除非有明确缓存和超时设计。

部署：
- docker compose 至少包含 frontend、backend、worker、review-mcp；
- MCP Streamable HTTP 只通过受控内部或鉴权入口暴露；
- 配置健康检查、依赖顺序、超时和资源限制；
- 模型缓存、Chroma/索引、上传、报告和数据库使用明确持久化目录；
- 生产禁止默认密钥、DEBUG、宽松 CORS 和 legacy V1 API；
- 先完成本地 production compose 验收；
- 公网部署涉及服务器、域名、DNS、证书和真实密钥时，列出用户必须完成的步骤，不伪造公网已上线状态。

文档：
- README 首屏改为工程投标资料证据化辅助审查 Agent；
- general 作为旧版区域简短说明，不再占据主叙事；
- 更新系统架构、Agent 状态机、MCP 工具调用、评测方法、实际指标、限制和演示命令；
- 更新 docs/DEMO_SCRIPT.md、RESUME.md、INTERVIEW_QA.md、TESTING.md 和部署文档；
- 所有指标引用本次评测输出文件；
- 不写“生产级”“自动合规”“零幻觉”等无法证明的词；
- 简历表述使用真实指标，不使用路线图目标值。

版本收口：
- 只有测试、E2E、评测和本地 production compose 均通过后，才更新 VERSION 与 CHANGELOG；
- 不自动创建 Git tag、commit、push 或 PR；
- 记录仍需用户完成的公网基础设施事项。

验收标准：
- 工程黄金案例可从头到尾复现；
- 所有公开指标可由命令重新计算；
- MCP 故障和局部重试有 E2E 证据；
- 用户隔离和安全边界通过；
- README、简历和源码完全一致；
- 公网部署若尚未由用户提供基础设施，明确标记未完成，不得声称已上线。
```

---

## 每个阶段结束后给 Codex 的复核提示词

如果某个阶段声称完成，再单独发送下面这段进行验收：

```text
请只验收刚完成的阶段，不新增功能。

1. 读取 AGENTS.md、该阶段提示词和 git diff；
2. 检查是否覆盖了用户原有未提交改动；
3. 把每项验收标准映射到具体代码、测试或实际运行证据；
4. 运行最小必要验证；
5. 查找 README、接口、配置、测试与源码之间的不一致；
6. 将问题按“阻断验收 / 应修复 / 可延后”分级；
7. 只报告问题，不直接修改文件，等待我确认。

没有实际运行的验证不得标记为通过。若全部通过，明确写出“本阶段验收通过”及证据；否则明确写“本阶段未通过”。
```
