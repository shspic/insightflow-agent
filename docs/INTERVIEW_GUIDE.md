# InsightFlow Agent 面试材料

## 1. 为什么不是普通聊天机器人？

聊天机器人是「用户输入 → 模型返回文本」。本项目是任务执行系统：上传文件后，系统做「任务判断 → 确定性抽取 → 规则校验 → LLM 规划核验 → 质量门 → 报告交付」的闭环。关键差异：**不信任模型输出直接进结果**——中间有确定性管道、规则引擎、质量门和人工候选采纳边界，过程全部可观测可审计。

## 2. Agent 如何规划和调用工具？

Verification Agent：DeepSeek 接收结构化 planner 输入（Finding/evidence/规则上下文），输出工具调用计划（白名单内：检索工具 + MCP 工具），然后按计划执行；计划无效或模型失败时回退到确定性 planner（`planner_type=deterministic_fallback`，如实记录 fallback）。工具调用有预算上限（max_verification_tool_calls），防失控。

## 3. MCP 为什么需要 capability token？

MCP Server 是独立服务，客户端调用时不能只靠共享密钥（一旦泄露不可撤销、无法区分调用者）。capability token 是服务端为真实 user_id 签发的短期 HMAC 签名 Bearer（sub=user_id、exp 过期、nonce），中间件校验签名与有效期，服务端再从认证 subject 解析调用者，**不信任工具参数里的 owner_user_id**，实现调用者身份隔离。内部共享密钥不直接作为 Bearer（格式校验不过）。

## 4. BM25 / BGE / RRF 如何组合？

- BM25：稀疏关键词，快速精确匹配术语；
- BGE：稠密向量，捕获语义相似；
- RRF（Reciprocal Rank Fusion）：对两路排序的倒序排名做融合 `sum 1/(k+rank)`，取 top-K，避免归一化分数失真。
- 语料按文件类型确定性分块（PDF 分页窗口、Excel 行区间、Markdown 分节），chunk_id 稳定可复现。
- 真实评测（真实 BGE）：overall recall@3=0.7632、recall@5=0.8553、mrr=0.7210。

## 5. Evidence 与 CorpusChunk 哈希语义？

两个独立概念：
- `Evidence.content_hash` = **记录哈希**：`{file_id, locator, quote}` 元数据 JSON 的 SHA-256，防证据记录被篡改；
- `CorpusChunk.content_hash` = **文本块哈希**：`sha256(chunk.text)`，识别语料内容变化。
- 修复前缺陷：有人把两者直接比较（语义错位）。修复：新增独立来源字段（provenance_type / source_file_hash / source_chunk_id / source_chunk_hash），Gate 先复算记录哈希，再分别核对文件字节哈希与 locator/chunk 锚点；历史证据缺来源 → 独立稳定错误 `EVIDENCE_PROVENANCE_MISSING` → needs_human。

## 6. 为什么候选证据必须人工采纳？

检索命中只是「候选」，可能是噪声或过时语料。直接采纳会把 LLM/检索错误固化为正式证据。因此：候选带边界标记（candidate_only + requires_human_confirmation），人工接受前服务端**重新校验**（corpus/index SHA 未变、chunk_id 在当语料重新定位、quote 重新生成、来源哈希服务端计算），接受 = Evidence + Finding 绑定 + 决策单事务原子提交；拒绝只写决策。Supervisor 自动流程永不自动采纳候选。

## 7. Supervisor 如何避免模型越权？

- Supervisor 是确定性状态机（四节点），只根据结构化状态/错误码/质量门结果决策，不新增第二次 LLM 规划；
- 不修改 Finding/Evidence/历史 Report；不自动接受候选证据；不自动生成新报告；
- 幂等复用仅限成功状态（needs_human/failed 不伪装成功）；
- 质量门失败或 needs_information 时严禁生成报告。

## 8. Quality Gate 如何阻止无证据结论？

对每个 Finding 的每个 Evidence：规则快照匹配 → 归属校验 → 记录哈希复算 → 来源完整性（文件哈希 + locator/chunk）→ input snapshot 契约（存在、SHA 一致、必需字段在场）→ 数字结论必须有 `engine:<rule_id>` 计算来源。任一失败 → finding 进入 need_more_info → Supervisor needs_human，不生成报告。错误码稳定（EVIDENCE_STALE / EVIDENCE_PROVENANCE_MISSING / INPUT_SNAPSHOT_MISMATCH 等），可测试可审计。

## 9. 幂等、局部重试、审计链？

- 幂等：Supervisor 以 input_state_hash（覆盖 findings/evidences/corpus/index/版本参数）做成功态复用；ReviewRun 快照（规则/Brief/输入）哈希校验；
- 局部重试：MCP 瞬时错误（UNAVAILABLE/TIMEOUT）只重试失败工具一次，成功节点不重复；真实故障注入实测 rate=1.0；
- 审计链：ReviewSupervisorStep（attempt_number/retry_of_id/error_code/耗时）、ReviewToolCall（attempt/retry_of/input/output）、候选决策（只追加）、input snapshot——每一步可复现。

## 10. SQLite 的适用范围与升级方向？

适用：单机/低频/演示/中小数据。已做：WAL、busy timeout、外键、租约式单 Worker。限制：写并发、跨进程多写锁竞争。升级方向：PostgreSQL + 连接池（SQLAlchemy 已抽象，主要工作量在类型与全文检索）、对象存储（uploads/reports 换 S3/OSS）、任务队列换 Redis/Celery。属已知限制，不夸大。

## 11. Docker / CI / Playwright 的工程价值？

- Docker：非 root（uid 10001）、只读根文件系统（生产 compose）、启动 entrypoint 幂等迁移、volume 持久化 SQLite/uploads/reports/retrieval、不复制密钥/模型缓存进镜像、BGE 模型不自动下载；
- CI：三线 GitHub Actions（后端固定依赖 + Alembic + 791 测试；前端 npm ci/test/build；Playwright 浏览器冒烟），并发取消 + 最小权限，CI 默认不调真实 LLM、不下载真实 BGE；
- Playwright：真实浏览器验收（登录/核验/发现/报告/下载/跨用户隔离/390px 移动端），失败自动保留截图/trace/video。

## 12. 真实评测指标如何解释？

- 检索指标：真实 BGE 混合检索，44 条冻结查询拆 development 20 / validation 8 / test 16；recall@3 衡量「前 3 个结果覆盖相关语料」的比例，no-answer 查询按「是否误返回结果」计 FP；
- Supervisor 指标：字段抽取 F1=0.8696（确定性管道对黄金字段）、问题识别 F1=1.0（12/12 规则命中）、引用定位 0.5833、content_hash 复算 14/14、无证据结论率 0.0；
- 这些是工程指标，说明「管道可复现、门控有效、检索可量化」，不等于业务准确率声明。

## 13. 项目不足和后续规划？

- 不足：SQLite 单机、单 Worker、确定性规则覆盖面有限、真实 BGE 依赖模型缓存、未公网部署；
- 规划：PostgreSQL 化、更多规则类型与黄金数据集、检索评测指标提升（验证集 recall@3 0.6429 → 目标 0.8+）、公网部署与 TLS、对象存储。
