# V3 检索评测基线报告

> 数据集: engineering-review-v1 v1.1.0
> 评测时间: 2026-08-07T08:50:11.815083+00:00
> split: dev | modes: keyword, tfidf, bm25
> 合成演示数据，不作为真实招投标、工程、资质或法律判断依据。

## 1. 元数据

- 数据集名称: engineering-review-v1
- 数据集版本: v1.1.0
- 查询集 SHA-256: `14b0695280a624cef8e4c9a01c70d49782f270580634ea19f91e7880c852e23d`
- 语料 SHA-256: `05da389fade896f65196ced5744623fd05d099f2432591ce867f93523dd31c8c`
- manifest SHA-256: `b986177c483736fb8ec89bc9fbbf69dd1d662aa99fa6c401af9b010c873d9cf9`
- tokenizer: v3_tokenizer v1.0.0
- chunking: v1.0.0

### 运行环境 / 可追溯信息

- Python: 3.14.4
- Platform: Windows-11-10.0.26200-SP0
- Git commit: `18a39c17`
- Git branch: codex/stage-4a
- Git working tree: dirty
  > ⚠ 当前工作树存在未提交改动，报告由未提交源码生成，`git_commit` 不包含 Stage 4A 评测代码。
- Evaluation code SHA-256: `e055f5c4ecdc637f696e1ee4c24afc9d69e8fe71fdd6b486a3b76027ca199ebe`
- Query file SHA-256: `14b0695280a624cef8e4c9a01c70d49782f270580634ea19f91e7880c852e23d`
- Corpus SHA-256: `05da389fade896f65196ced5744623fd05d099f2432591ce867f93523dd31c8c`
- Manifest SHA-256: `b986177c483736fb8ec89bc9fbbf69dd1d662aa99fa6c401af9b010c873d9cf9`

### 评测源码文件

| 文件 | SHA-256 |
| --- | --- |
| `backend/app/evaluation/v3_corpus.py` | `bf41e2843d900e92...` |
| `backend/app/evaluation/v3_metrics.py` | `b4d75374bec00924...` |
| `backend/app/evaluation/v3_query_set.py` | `f1577f3ec79ecd98...` |
| `backend/app/evaluation/v3_retrieval.py` | `c3103cd9f499c192...` |
| `backend/app/evaluation/v3_retrieval_runner.py` | `5a592666e2cd0e70...` |
| `backend/app/evaluation/v3_tokenizer.py` | `ca73240c290e0912...` |

## 2. 语料概览

- 分块总数: 17

| chunk_id | file_role | file_name | locator | len | content_hash |
| --- | --- | --- | --- | --- | --- |
| C0001 | tender_requirement | 01_合成招标要求.pdf | pdf_page p1 | 187 | `5fdee84267c92d4b...` |
| C0002 | tender_requirement | 01_合成招标要求.pdf | pdf_page p2 | 240 | `6a601ee6d2a73abe...` |
| C0003 | tender_requirement | 01_合成招标要求.pdf | pdf_page p3 | 206 | `dad52c0ba2d20529...` |
| C0004 | tender_requirement | 01_合成招标要求.pdf | pdf_page p4 | 196 | `891a8a9d31e12a1c...` |
| C0005 | tender_requirement | 01_合成招标要求.pdf | pdf_page p5 | 147 | `2c48f927affd58a2...` |
| C0006 | tender_requirement | 01_合成招标要求.pdf | pdf_page p6 | 91 | `718baa4201bcd753...` |
| C0007 | bid_response | 02_合成投标响应.pdf | pdf_page p1 | 226 | `24183a973c29d7e0...` |
| C0008 | bid_response | 02_合成投标响应.pdf | pdf_page p2 | 183 | `c5b1dbd29193f5e2...` |
| C0009 | bid_response | 02_合成投标响应.pdf | pdf_page p3 | 161 | `f935d68c6ff068b3...` |
| C0010 | bid_response | 02_合成投标响应.pdf | pdf_page p4 | 171 | `16b6d48eeb38d716...` |
| C0011 | qualification_attachment | 04_合成资质附件.pdf | pdf_page p1 | 261 | `4c8c10ea147df2b1...` |
| C0012 | qualification_attachment | 04_合成资质附件.pdf | pdf_page p2 | 3 | `58c0e7476a0d98d7...` |
| C0013 | personnel_equipment_data | 03_人员设备清单.xlsx | spreadsheet_cell [项目概况] A1:D7 | 157 | `16c2fb9a6ba3a353...` |
| C0014 | personnel_equipment_data | 03_人员设备清单.xlsx | spreadsheet_cell [人员清单] A1:F8 | 183 | `aee6bb9f6ef12db4...` |
| C0015 | personnel_equipment_data | 03_人员设备清单.xlsx | spreadsheet_cell [设备清单] A1:G7 | 221 | `e6b8125274d194a5...` |
| C0016 | personnel_equipment_data | 03_人员设备清单.xlsx | spreadsheet_cell [数据说明] A1:A9 | 234 | `00e2ab6cf3c04a55...` |
| C0017 | clarification_document | 05_项目澄清.md | text_chunk idx=0 | 496 | `7ca6af752ed43bc9...` |

## 3. 查询统计

- 总数: 28 (可回答: 25, 无答案: 3)
- top_k: 20

## 4. 基线对比（可回答查询）

| 指标 | 关键词检索 | TF-IDF | Okapi BM25 |
| --- | --- | --- | --- |
| Recall@3 | 0.6000 | 0.7600 | 0.8200 |
| Recall@5 | 0.7800 | 0.8600 | 0.8400 |
| MRR | 0.5210 | 0.6724 | 0.6770 |
| 延迟均值 (ms) | 0.1 | 3.3 | 2.1 |
| 延迟 P50 (ms) | 0.1 | 3.1 | 2.1 |
| 延迟 P95 (ms) | 0.2 | 4.0 | 2.5 |

## 5. 无答案查询指标

| 指标 | 关键词检索 | TF-IDF | Okapi BM25 |
| --- | --- | --- | --- |
| 查询数 | 3 | 3 | 3 |
| 拒绝数 | 0 | 0 | 0 |
| 误报数 | 3 | 3 | 3 |
| 误报率 | 1.0000 | 1.0000 | 1.0000 |

> 当前阶段无阈值机制，所有方法对所有查询返回结果，false_positive_rate 预期为 1.0。

## 6. 按类别指标

### 关键词检索

| category | count | Recall@3 | Recall@5 | MRR |
| --- | --- | --- | --- | --- |
| bid_info | 5 | 0.2000 | 0.7000 | 0.4067 |
| clarification | 2 | 1.0000 | 1.0000 | 1.0000 |
| clause_ref | 3 | 0.6667 | 1.0000 | 0.5278 |
| cross_file | 1 | 0.0000 | 0.0000 | 0.1429 |
| equipment | 2 | 0.0000 | 0.2500 | 0.1500 |
| numeric | 1 | 1.0000 | 1.0000 | 1.0000 |
| personnel | 2 | 0.0000 | 0.2500 | 0.1500 |
| qualification | 2 | 1.0000 | 1.0000 | 0.4166 |
| tender_spec | 7 | 1.0000 | 1.0000 | 0.6905 |

### TF-IDF

| category | count | Recall@3 | Recall@5 | MRR |
| --- | --- | --- | --- | --- |
| bid_info | 5 | 0.7000 | 0.9000 | 0.6333 |
| clarification | 2 | 1.0000 | 1.0000 | 1.0000 |
| clause_ref | 3 | 1.0000 | 1.0000 | 0.8333 |
| cross_file | 1 | 0.0000 | 0.5000 | 0.2000 |
| equipment | 2 | 0.0000 | 0.5000 | 0.1666 |
| numeric | 1 | 1.0000 | 1.0000 | 1.0000 |
| personnel | 2 | 0.2500 | 0.2500 | 0.2222 |
| qualification | 2 | 1.0000 | 1.0000 | 0.6666 |
| tender_spec | 7 | 1.0000 | 1.0000 | 0.8333 |

### Okapi BM25

| category | count | Recall@3 | Recall@5 | MRR |
| --- | --- | --- | --- | --- |
| bid_info | 5 | 0.8000 | 0.8000 | 0.7000 |
| clarification | 2 | 1.0000 | 1.0000 | 1.0000 |
| clause_ref | 3 | 1.0000 | 1.0000 | 0.8333 |
| cross_file | 1 | 0.0000 | 0.5000 | 0.2000 |
| equipment | 2 | 0.5000 | 0.5000 | 0.3000 |
| numeric | 1 | 1.0000 | 1.0000 | 1.0000 |
| personnel | 2 | 0.2500 | 0.2500 | 0.2291 |
| qualification | 2 | 1.0000 | 1.0000 | 0.6666 |
| tender_spec | 7 | 1.0000 | 1.0000 | 0.7619 |

## 7. 失败案例

- 总记录: 16 (mode-query)
- 唯一失败 query: 6

| query_id | split | mode | failure_type | recall@5 | mrr | retrieved |
| --- | --- | --- | --- | --- | --- | --- |
| Q011 | dev | keyword | recall_at_5_miss | 0.0000 | 0.1000 | C0017, C0003, C0002 |
| Q013 | dev | keyword | recall_at_5_miss | 0.0000 | 0.1000 | C0005, C0017, C0002 |
| Q022 | dev | keyword | recall_at_5_miss | 0.0000 | 0.1429 | C0017, C0002, C0003 |
| Q039 | dev | keyword | no_answer_false_positive | 0.0000 | 0.0000 | C0002, C0003, C0017 |
| Q040 | dev | keyword | no_answer_false_positive | 0.0000 | 0.0000 | C0017, C0002, C0005 |
| Q043 | dev | keyword | no_answer_false_positive | 0.0000 | 0.0000 | C0017, C0011, C0002 |
| Q011 | dev | tfidf | recall_at_5_miss | 0.0000 | 0.1111 | C0003, C0002, C0017 |
| Q013 | dev | tfidf | recall_at_5_miss | 0.0000 | 0.0833 | C0005, C0006, C0009 |
| Q039 | dev | tfidf | no_answer_false_positive | 0.0000 | 0.0000 | C0005, C0003, C0002 |
| Q040 | dev | tfidf | no_answer_false_positive | 0.0000 | 0.0000 | C0017, C0005, C0008 |
| Q043 | dev | tfidf | no_answer_false_positive | 0.0000 | 0.0000 | C0011, C0004, C0017 |
| Q011 | dev | bm25 | recall_at_5_miss | 0.0000 | 0.1250 | C0003, C0002, C0017 |
| Q013 | dev | bm25 | recall_at_5_miss | 0.0000 | 0.1000 | C0002, C0005, C0009 |
| Q039 | dev | bm25 | no_answer_false_positive | 0.0000 | 0.0000 | C0003, C0005, C0016 |
| Q040 | dev | bm25 | no_answer_false_positive | 0.0000 | 0.0000 | C0017, C0008, C0011 |
| Q043 | dev | bm25 | no_answer_false_positive | 0.0000 | 0.0000 | C0011, C0017, C0004 |

## 8. 玩具案例公式验证

- Recall@3: [PASS] (0.3333 vs 期望 0.3333)
- Recall@5: [PASS] (0.6667 vs 期望 0.6667)
- MRR: [PASS] (0.5 vs 期望 0.5)
- no-answer FP: [PASS]
- answerable/no-answer 分母互不污染: [PASS]

---
*报告生成时间: 2026-08-07T08:50:11.815083+00:00*