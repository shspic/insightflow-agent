# 项目截图清单

这个文件用于规划 InsightFlow Agent 上传 GitHub、录屏演示和面试展示时需要补充的截图。当前阶段不放真实截图，只保留 `screenshots/` 目录和 `.gitkeep` 占位。

截图建议统一放在项目根目录：

```text
screenshots/
```

## 截图总表

| 序号 | 建议文件名 | 截图内容 | 截图目的 | 是否适合放入 README |
| --- | --- | --- | --- | --- |
| 1 | `01-dashboard.png` | 首页 / Dashboard，展示项目名称、导航入口、后端连接状态。 | 让访问者第一眼理解项目是完整应用，不是单接口 Demo。 | 是 |
| 2 | `02-upload.png` | 文件上传页面，包含选择文件、上传按钮和已上传文件列表。 | 展示文件上传与管理能力。 | 是 |
| 3 | `03-file-parse.png` | 文件解析成功状态，展示字段名、行数、列数、缺失值和前 5 行预览。 | 展示 CSV / Excel 解析能力。 | 是 |
| 4 | `04-data-analysis.png` | 数据分析结果，展示字段类型、数值统计、文本高频值、缺失值统计。 | 展示 Pandas 数据分析能力。 | 是 |
| 5 | `05-charts.png` | 图表生成结果，展示缺失值柱状图、数值统计图或分类 Top 5 图。 | 展示后端生成图表并由前端展示。 | 是 |
| 6 | `06-agent-task.png` | Agent 任务执行页面，展示文件选择、自然语言输入和最终回答。 | 展示自然语言任务入口和结果闭环。 | 是 |
| 7 | `07-agent-trace.png` | Agent 执行轨迹，展示 `classify_task`、`plan_task`、`route_tools`、`execute_tool`、`write_result`、`save_result`。 | 展示 Agent 可观测性和工具调用过程。 | 是 |
| 8 | `08-pdf-rag.png` | PDF RAG 问答结果，展示问题、回答、页码和引用片段。 | 展示文档检索问答和引用来源。 | 是 |
| 9 | `09-image-ocr.png` | 图片 OCR 识别结果，展示图片文件、识别文本或 OCR 未配置提示。 | 展示多模态图片文字处理能力。 | 是 |
| 10 | `10-report-view.png` | Markdown 报告展示页，展示任务说明、文件概况、数据概况、图表、引用和结论。 | 展示报告生成能力。 | 是 |
| 11 | `11-report-download.png` | 报告下载按钮和下载后的 `.md` 文件。 | 展示报告可落地保存。 | 可选 |
| 12 | `12-docker-compose.png` | 终端中 `docker compose up --build` 成功启动前端和后端。 | 展示项目可一键启动。 | 可选 |
| 13 | `13-swagger.png` | FastAPI Swagger 页面，展示 `/api/health`、`/api/files`、`/api/tasks`、`/api/reports`。 | 展示后端 API 完整度。 | 可选 |
| 14 | `14-github-readme.png` | GitHub README 页面，展示项目简介、架构图、功能列表和启动说明。 | 展示仓库包装效果。 | 不需要 |

## README 推荐截图顺序

README 中建议最多放 5 到 7 张核心截图，避免页面过长：

1. `01-dashboard.png`
2. `02-upload.png`
3. `04-data-analysis.png`
4. `05-charts.png`
5. `07-agent-trace.png`
6. `08-pdf-rag.png`
7. `10-report-view.png`

如果 README 只放 3 张，优先选择：

1. `02-upload.png`
2. `07-agent-trace.png`
3. `10-report-view.png`

## 截图注意事项

- 不要在截图中暴露真实 API Key、真实 `.env` 内容、私人路径或隐私文件名。
- 不要使用包含真实业务数据的文件，优先使用测试 CSV、测试 PDF 和测试图片。
- 截图前先清理浏览器地址栏中不必要的本机路径信息。
- 如果 Docker OCR 未配置，图片 OCR 截图可以展示明确错误提示，这属于当前限制，不需要伪造成功结果。
- 不要把尚不存在的图片链接插入 README，等截图文件真实存在后再补链接。
- 截图尺寸建议保持一致，优先使用 1440px 宽度或常见笔记本屏幕宽度。
