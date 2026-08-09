# Stage 6A 端到端评测报告

- dataset: engineering-review-v1 v1.1.0
- case: SYN-ENG-2026-001
- commit: d56cf6d4922edebd45a544bbc647efdda373bcc2 (codex/stage-6a, dirty=True)
- python: 3.14.4 / Windows-11-10.0.26200-SP0
- evaluated_at: 2026-08-09T16:57:03

## 冻结 SHA

| 对象 | SHA-256 |
| --- | --- |
| 01_合成招标要求.pdf | `fc9cde98c2c95eab3719bca176cdbf17328ef18b19783b70fb9536ca7b5db6a9` |
| 02_合成投标响应.pdf | `9715dd74a638c30cf539fa56d0a0f1548308ed845a0a0adf6966a3525d443079` |
| 03_人员设备清单.xlsx | `12c9b8ddec25d814d36939347f57a9b5306c11c9e7aba012b1a12e6d26d30c27` |
| 04_合成资质附件.pdf | `f2f73f3b47ca01ae6a4131069846a2ae9c197245813ae89e3a254f1ed3583c7b` |
| 05_项目澄清.md | `ec454cc78881e3dffb36bedc5bef800f7da65758f47c7802c2117dfadd2a6ce8` |
| manifest.json | `b986177c483736fb8ec89bc9fbbf69dd1d662aa99fa6c401af9b010c873d9cf9` |
| ground_truth.json | `20d941669911f169867776593e7e903d8cb37d06cc0be166ef13c64e42a0249b` |
| retrieval_queries.json | `d3b1cc8768e6d0a715f4fbe97332c36e05f04041818592632148df3a40041cac` |
| review_brief.json | `59e7b7f43bc39cea93d6c1e1f9bf18ec8967936068824081cbc6bd950d8da80b` |
| rule_pack | `bdb63c023f944393c878bd1c69bc53f9d87b344fbb33ec7d0db0c4d0878ba53a` |
| evaluation_code | `037e8595786f49fe45f70d0e99e6f6f9f06f3f22324ff82a4172fbc66e9b2c55` |

## 指标

```json
{
 "answerable": {
  "answerable_count": 7,
  "recall@3_mean": 0.6429,
  "recall@5_mean": 0.8571,
  "mrr_mean": 0.6357,
  "count": 7,
  "mean_ms": 14.7471,
  "p50_ms": 14.41,
  "p95_ms": 17.16
 },
 "no_answer": {
  "no_answer_count": 1,
  "false_positive_count": 1,
  "false_positive_rate": 1.0
 }
}
```

## 失败案例（15）

- **RETRIEVAL_MISS** (RECALL) Q012: recall@5=0.5
- **RETRIEVAL_MISS** (RECALL) Q013: recall@5=0.0
- **RETRIEVAL_MISS** (RECALL) Q022: recall@5=0.5
- **RETRIEVAL_MISS** (RECALL) Q025: recall@5=0.5
- **RETRIEVAL_MISS** (RECALL) Q026: recall@5=0.5
- **RETRIEVAL_MISS** (RECALL) Q028: recall@5=0.0
- **RETRIEVAL_MISS** (RECALL) Q029: recall@5=0.5
- **RETRIEVAL_MISS** (RECALL) Q030: recall@5=0.5
- **RETRIEVAL_MISS** (RECALL) Q031: recall@5=0.5
- **NO_ANSWER_FALSE_POSITIVE** (NO_ANSWER) Q039: no-answer 查询返回了结果
- **NO_ANSWER_FALSE_POSITIVE** (NO_ANSWER) Q040: no-answer 查询返回了结果
- **NO_ANSWER_FALSE_POSITIVE** (NO_ANSWER) Q041: no-answer 查询返回了结果
- **NO_ANSWER_FALSE_POSITIVE** (NO_ANSWER) Q042: no-answer 查询返回了结果
- **NO_ANSWER_FALSE_POSITIVE** (NO_ANSWER) Q043: no-answer 查询返回了结果
- **NO_ANSWER_FALSE_POSITIVE** (NO_ANSWER) Q044: no-answer 查询返回了结果