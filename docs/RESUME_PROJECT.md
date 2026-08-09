# InsightFlow Agent：简历项目描述

## 一句话介绍

基于 FastAPI + React 构建的「多模态文档与数据分析 + 工程投标审查」AI 任务执行平台：确定性审查管道、LLM 核验、MCP 工具调用、四节点 Supervisor 与质量门控，791 项后端测试与 103 项前端测试全部通过。

## 简历 Bullet（3～5 条）

1. 基于 FastAPI + React + SQLite 构建全栈 AI 任务执行平台，两条主线：通用多模态文档分析（五类文件解析、Pandas 分析、RAG、图表、三格式报告）与工程投标审查（招标要求/投标响应/人员设备清单/资质附件一致性核验）。
2. 设计确定性 Review Pipeline（字段抽取 + 六类规则引擎 + Evidence 精确绑定），并用 Supervisor 四节点状态机（extraction→verification→quality_review→reporting）编排 DeepSeek 规划核验与报告生成；Quality Gate 对证据记录哈希、来源文件哈希、语料定位与输入快照逐项复算，阻止无锚结论进入报告。
3. 实现官方 Streamable HTTP MCP 工具服务（一致性检查/规则检索），短期签名 capability token 认证 + 服务端归属二次校验；仅瞬时错误局部重试（实测重试成功率 1.0），attempt/retry_of/error_code 全链路审计。
4. 构建 BM25 + BGE 稠密检索 + RRF 融合的工程语料检索，候选证据必须人工采纳（采纳前服务端重新定位与哈希校验，单事务原子提交）；真实 BGE 评测 overall recall@3=0.7632 / recall@5=0.8553。
5. 工程化交付：GitHub Actions 三线 CI（后端 791 测试 + Alembic 迁移、前端 npm ci/test/build、Playwright 浏览器冒烟）、Docker 多阶段镜像与 Compose 生产部署（非 root、只读根文件系统、启动自动迁移）、13 张真实浏览器验收截图。

## 技术栈

- 后端：Python、FastAPI、Uvicorn、SQLAlchemy、SQLite（WAL）、Alembic、Pydantic、Pandas、PyMuPDF、pytest
- 前端：React 19、Vite 7、React Router、Axios、CSS 设计 Token（深/浅色）、Vitest（node:test）
- AI 能力：DeepSeek（Verification 规划）、BGE（sentence-transformers）、MCP（Streamable HTTP）、BM25+RRF、确定性规则引擎
- 工程：GitHub Actions、Docker/Compose、Nginx 反代（HTTPS/SSE/SPA）、Playwright、SQLite 备份脚本

## 量化指标（全部为真实实测数据）

| 指标 | 数值 |
| --- | --- |
| 后端测试 | 791 passed（含 Alembic 全链迁移 16 项） |
| 前端测试 | 103 passed；`npm run build` 通过 |
| 浏览器冒烟 | Stage 6B 3 passed（真实浏览器黄金案例复核）+ Stage 6C CI 冒烟 4 passed |
| 真实检索评测 | overall recall@3=0.7632、recall@5=0.8553、mrr=0.7210（真实 BGE，38 answerable） |
| Supervisor | 四节点全 success、Quality Gate passed、Markdown+PDF 双资产、DB/磁盘 SHA 一致 |
| MCP 局部重试 | 真实故障注入 local_retry_success_rate=1.0 |
| 数据规模 | 44 条冻结评测查询（development 20 / validation 8 / test 16）、14 条确定性规则、5 类黄金材料 |

## 亮点（面试深挖点）

- **Agent 工作流**：不是把输入发给模型返回文本，而是「判断任务 → 确定性抽取 → 规则校验 → LLM 规划核验 → 质量门 → 报告」的完整决策-执行-验证闭环；
- **MCP 与安全**：Streamable HTTP + capability token（短期 HMAC 签名、subject=真实用户），服务端不信任客户端身份参数；
- **哈希语义分离**：Evidence 记录哈希 vs Corpus 文本块哈希是两个独立概念，Quality Gate 分层复算，杜绝"哈希对不上就放行/误杀"两类错误；
- **质量门控**：历史证据缺来源字段 → 独立错误 `EVIDENCE_PROVENANCE_MISSING` → needs_human，禁止静默放行；
- **可观测与审计**：每步 attempt/retry/error_code、input snapshot、规则快照、Brief 快照全部持久化，可复现可回滚。

## 精简版（Boss/拉勾/简历 PDF）

> **InsightFlow Agent｜全栈 AI Agent 平台（FastAPI + React）**
> 多模态文档分析与工程投标审查双主线。确定性 Review Pipeline + 六类规则引擎，Supervisor 四节点编排 DeepSeek 核验与 MCP 工具，Quality Gate 对证据哈希/来源/快照复算把关，候选证据人工采纳闭环。BM25+BGE+RRF 检索（真实评测 recall@3=0.76）。791 后端 + 103 前端测试，GitHub Actions 三线 CI，Docker Compose 生产部署（非 root/自动迁移）。13 张真实浏览器验收截图。

## 英文项目描述（附录）

> **InsightFlow Agent — Full-stack AI Agent platform (FastAPI + React)**
> A task-execution AI application with two product lines: general multimodal document analysis and engineering bid-review. A deterministic review pipeline with a 6-rule engine feeds a 4-node Supervisor (extraction → verification → quality_review → reporting) that orchestrates DeepSeek planning, Streamable-HTTP MCP tools, and hybrid BM25+BGE+RRF retrieval. A deterministic Quality Gate re-computes evidence hashes, source-file hashes, locators and input snapshots before any report is generated; retrieval candidates become evidence only after human acceptance with server-side re-validation. Measured: 791 backend + 103 frontend tests, real-BGE retrieval recall@3=0.7632, MCP local-retry success rate 1.0, GitHub Actions CI (backend/frontend/Playwright) and Docker Compose production deployment (non-root, read-only rootfs, auto-migrations).

> 说明：本项目是面向简历展示的中等规模全栈项目，非生产级大规模系统；SQLite 单机部署、单 Worker 队列、确定性规则优先，均为有意识的设计取舍。
