# 工程检测服务投标资料审查——黄金案例 v1

> **合成演示数据，不作为真实招投标、工程、资质或法律判断依据。**

## 概述

本目录包含 InsightFlow V3 工程审查主线的首个黄金演示案例 `SYN-ENG-2026-001`。

所有材料由 `scripts/generate_engineering_review_fixture.py` 使用固定数据生成，可重复运行且输出一致。

## 材料清单

| 文件 | 角色 | 内容 |
|------|------|------|
| `01_合成招标要求.pdf` | tender_requirement | 14 条合成招标条款（~6 页） |
| `02_合成投标响应.pdf` | bid_response | 注入 5 个问题的合成投标（~4 页） |
| `03_人员设备清单.xlsx` | personnel_equipment_data | 4 工作表，含人员/设备/数据说明 |
| `04_合成资质附件.pdf` | qualification_attachment | 有效期不足的资质文件（第2页为扫描图） |
| `05_项目澄清.md` | clarification_document | 2 条澄清条款 |
| `manifest.json` | — | 文件哈希与元数据 |
| `ground_truth.json` | — | 12 个预期问题 + 2 个通过规则 |
| `review_brief.json` | — | 结构化审查意图标准答案 |

## 注入的 12 个问题

| 编号 | 规则 | 严重度 | 摘要 |
|------|------|--------|------|
| SYN-REQ-001 | required_field | high | 投标响应项目名称为空 |
| SYN-REQ-002 | required_field | high | 人员清单项目负责人姓名为空 |
| SYN-EQ-001 | cross_file_equal | high | 两份文件项目名称不一致 |
| SYN-EQ-002 | cross_file_equal | high | 证书编号不一致 |
| SYN-NUM-001 | numeric_threshold | medium | 人员 4 < 5 |
| SYN-NUM-002 | numeric_threshold | high | 报价 2,150,000 > 2,000,000 |
| SYN-NUM-003 | numeric_threshold | medium | 设备 3 < 4 |
| SYN-DATE-001 | date_order | high | 资质 2027-06-30 < 2027-12-31 |
| SYN-DATE-002 | date_order | medium | 签署 2026-10-02 > 2026-09-30 |
| SYN-DATE-003 | date_order | medium | 校准 2026-12-31 < 2027-12-31 |
| SYN-EVD-001 | evidence_required | medium | 负责人姓名缺证据 |
| SYN-EVD-002 | evidence_required | medium | 扫描页证书编号缺文本层 |

## 预期通过规则

- SYN-DOC-001（资质附件已提交）
- SYN-DOC-002（人员设备清单已提交）

## 使用方式

重新生成材料：

```bash
cd /d/spir/NO2_agent
python scripts/generate_engineering_review_fixture.py
```

运行完整性测试：

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/test_v3_phase2b_fixture_integrity.py -v
```
