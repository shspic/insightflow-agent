# V2-05 自动评估指南

## 数据集

`v2-core` 是公开合成数据集，共 85 条：

| 分类 | 数量 |
| --- | ---: |
| 表格分析 | 15 |
| 多表对比 | 10 |
| PDF/Markdown 检索 | 15 |
| 跨表格与规则文档 | 10 |
| 图片和扫描 PDF OCR | 5 |
| 需求澄清 | 10 |
| 超范围和拒答 | 10 |
| 报告完整性 | 10 |

资源只有合成 CSV、Markdown 和一份可公开复现的扫描通知 SVG，不包含真实用户文件。

2026-07-24 的实际 deterministic 运行结果：85 条全部通过自动规则检查，平均响应 1ms、P95 1ms、平均模型调用 0、平均工具调用 1.65。该结果只证明确定性执行器、数据集加载、路由预期和持久化链路一致，不是 DeepSeek、真实 OCR 或人工报告质量准确率。

## deterministic 模式

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m app.evaluation.run_eval --dataset v2-core --mode deterministic
```

按类别：

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.run_eval `
  --dataset v2-core --mode deterministic --category document_retrieval
```

导出失败：

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.run_eval `
  --dataset v2-core --mode deterministic `
  --export-failures .\evaluation-output\failures.json
```

默认使用隔离的 `backend/data/evaluation.db`，不得设置为真实业务 `DATABASE_URL`。deterministic 不调用 DeepSeek，也不创建真实用户工作区。

## 指标

运行器计算分类、追问、计划完整、工具路由、工具成功、文件关系、数据结论、引用命中、拒答、报告章节、数字一致、Quality Review 拦截、任务成功、平均/P95 耗时、平均模型和工具调用数。

指标是从本次持久化 `evaluation_results` 计算，不能写死或虚构。确定性规则通过不代表真实模型质量；OCR 资源标识案例也不等于真实 OCR 精度测量。

## 自动规则与人工评审

自动规则适合检查路由、结构、引用标识、预算和拒答。以下仍需要人工评审：结论是否有用、语气、图表可读性、真实扫描 OCR、复杂宽表导出和行动建议质量。model 模式当前被安全关闭，必须在后续明确预算、隐私授权和隔离资源后单独实现。
