# 测试说明

## 1. 测试目标

本项目当前测试目标是保证核心工程结构可用、关键模块可导入、健康检查接口稳定、前端可以完成生产构建。测试优先覆盖轻量 smoke test，不依赖真实上传文件、真实 LLM API Key 或真实 OCR 引擎。

## 2. 后端测试范围

当前后端测试位于 `backend/tests/`：

- `test_health.py`：验证 `/api/health` 返回 200，且响应中包含 `status` 和 `app_name`。
- `test_config.py`：验证配置模块可以导入，默认配置存在，并且测试环境不会使用真实 API Key。
- `test_basic_services.py`：验证核心 service 模块可以正常导入，包括 `file_service`、`parser_service`、`analysis_service`、`chart_service`、`rag_service`、`report_service` 和 `llm_service`。

运行方式：

```powershell
cd backend
pytest
```

## 3. 前端构建测试

前端当前使用 Vite 构建，重点验证生产构建是否能正常完成。

运行方式：

```powershell
cd frontend
npm install
npm run build
```

## 4. Docker Compose 测试

本地 Docker Compose 用于验证前后端容器是否能一键启动。

运行方式：

```powershell
docker compose up --build
```

启动后访问：

- 前端：[http://localhost:5173](http://localhost:5173/)
- 后端：[http://localhost:8000](http://localhost:8000/)
- Swagger：[http://localhost:8000/docs](http://localhost:8000/docs)
- 健康检查：[http://localhost:8000/api/health](http://localhost:8000/api/health)

停止方式：

```powershell
docker compose down
```

## 5. 公网部署测试

公网演示地址：

- 前端：[https://insightflow-agent.vercel.app](https://insightflow-agent.vercel.app/)
- 后端：[https://insightflow-agent-spi.onrender.com](https://insightflow-agent-spi.onrender.com/)
- 健康检查：[https://insightflow-agent-spi.onrender.com/api/health](https://insightflow-agent-spi.onrender.com/api/health)
- Swagger：[https://insightflow-agent-spi.onrender.com/docs](https://insightflow-agent-spi.onrender.com/docs)

验证重点：

- Render 后端是否能从冷启动恢复。
- `/api/health` 是否返回正常。
- Swagger 是否能打开。
- Vercel 前端是否能访问 Render 后端。
- 浏览器控制台是否有 CORS 报错。

## 6. 手动验收清单

- `/api/health` 返回 `status: ok`。
- 文件上传成功，文件列表能显示新文件。
- CSV / Excel 可以解析字段、行列数、缺失值和预览数据。
- CSV / Excel 可以执行数据分析。
- CSV / Excel 可以生成图表。
- PDF 可以索引并执行 RAG 检索问答。
- 图片可以执行 OCR；如果环境没有 Tesseract，应返回清晰提示。
- 任务可以生成 Markdown 报告并下载。
- 多文件综合分析可以选择多个文件并返回综合结果。
- Agent 执行轨迹能展示分类、计划、路由、工具执行、写结果和保存结果。
- Docker Compose 可以启动前端和后端。
- Vercel 前端可访问。
- Render 后端 `/api/health` 和 `/docs` 可访问。

## 7. 当前未覆盖的测试

- 尚未覆盖真实文件上传的端到端自动化测试。
- 尚未覆盖 CSV / Excel 分析结果的精确断言。
- 尚未覆盖 PDF RAG 检索质量的自动化评估。
- 尚未覆盖 OCR 识别准确率评估。
- 尚未覆盖报告 Markdown 内容的快照测试。
- 尚未覆盖浏览器端 UI 自动化测试。
- 尚未覆盖 Render / Vercel 线上健康检查的自动化监控。

## 8. 后续测试增强方向

- 增加固定样例 CSV / Excel / PDF / 图片测试文件。
- 对分析结果、缺失值统计和图表结果做断言。
- 增加 RAG 检索评估集，验证页码和引用片段。
- 增加 OCR 样例图片和识别准确率记录。
- 使用 Playwright 增加前端核心流程测试。
- 增加 GitHub Actions 定期运行基础健康检查。
- 增加任务回归测试，防止 Agent 分类和工具路由退化。
