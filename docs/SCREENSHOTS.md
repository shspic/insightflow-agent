# 截图清单

这个文件用于记录后续上传 GitHub 或写简历时建议补充的项目截图。当前阶段不放真实截图，只保留截图目录占位。

建议截图放到项目根目录的 `screenshots/` 目录。

## 建议补充的截图

1. 首页或主导航截图
   - 展示项目名称 InsightFlow Agent。
   - 展示后端连接状态。

2. 文件上传页截图
   - 展示上传按钮。
   - 展示已上传文件列表。
   - 文件列表中包含文件 ID、文件名、类型、状态和上传时间。

3. CSV / Excel 解析结果截图
   - 展示字段名、行数、列数、缺失值统计和前 5 行预览。

4. 数据分析结果截图
   - 展示字段类型、数值列统计、文本列高频值和缺失值统计。

5. 图表生成截图
   - 展示缺失值统计图、数值统计图或分类 Top 5 图。

6. 工作区任务执行截图
   - 展示文件选择、自然语言任务输入和任务结果。

7. Agent 执行轨迹截图
   - 展示 `classify_task`、`plan_task`、`route_tools`、`execute_tool`、`write_result`、`save_result`。
   - 展示每一步状态、耗时、输入摘要和输出摘要。

8. PDF RAG 截图
   - 展示 PDF 检索问题。
   - 展示回答、页码和引用片段。

9. 图片 OCR 截图
   - 展示图片文件。
   - 展示 OCR 识别文本或未配置 OCR 的明确提示。

10. Markdown 报告页截图
    - 展示报告标题、任务说明、数据概况、图表、PDF 引用、OCR 结果和结论。

11. 报告下载截图
    - 展示下载按钮。
    - 展示下载得到的 `.md` 文件。

12. Docker 启动成功截图
    - 展示 `docker compose up --build` 后前端和后端启动日志。
    - 展示前端 `http://localhost:5173` 和后端 Swagger `http://localhost:8000/docs`。

## 截图命名建议

```text
screenshots/
  01-home.png
  02-upload.png
  03-table-parse.png
  04-data-analysis.png
  05-charts.png
  06-workspace-task.png
  07-agent-trace.png
  08-pdf-rag.png
  09-image-ocr.png
  10-report.png
  11-report-download.png
  12-docker-start.png
```

## 注意事项

- 不要在截图中暴露真实 API Key。
- 不要使用包含隐私信息的真实业务文件。
- 面试展示时优先使用小型测试文件，避免现场等待时间过长。
