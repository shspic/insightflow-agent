# 最终发布检查清单

## 1. 代码检查

- [ ] `git status` 只包含预期改动，发布前应为 clean。
- [ ] 没有提交 `backend/.env`。
- [ ] 没有提交 `backend/.venv/`。
- [ ] 没有提交 `backend/data/`。
- [ ] 没有提交 `backend/storage/uploads/`。
- [ ] 没有提交 `backend/storage/charts/`。
- [ ] 没有提交 `backend/storage/reports/`。
- [ ] 没有提交 `frontend/node_modules/`。
- [ ] 没有提交 `frontend/dist/`。
- [ ] 没有提交 `__pycache__/`。
- [ ] 没有提交 `*.pyc`。
- [ ] 没有提交 `.DS_Store`。
- [ ] README、docs 和配置文件中没有真实 API Key。

## 2. 本地运行检查

- [ ] 后端可以启动。
- [ ] 前端可以启动。
- [ ] `python -m app.db.init_db` 可以初始化数据库。
- [ ] `pytest` 可以运行。
- [ ] `npm run build` 可以通过。
- [ ] `docker compose up --build` 可以启动前端和后端。
- [ ] `docker compose down` 可以停止服务。

## 3. 功能检查

- [ ] 文件上传可用。
- [ ] CSV / Excel 解析可用。
- [ ] 数据分析可用。
- [ ] 图表生成可用。
- [ ] PDF RAG 可用。
- [ ] OCR 可用；如果环境缺少 Tesseract，应返回明确提示。
- [ ] Markdown 报告生成可用。
- [ ] 多文件综合分析可用。
- [ ] AgentTrace 能展示完整执行轨迹。
- [ ] LLM 未配置时 fallback 可用。

## 4. 部署检查

- [ ] Render `/api/health` 可访问。
- [ ] Render `/docs` 可访问。
- [ ] Vercel 前端可访问。
- [ ] 前端请求后端没有 CORS 报错。
- [ ] Vercel 已配置 `VITE_API_BASE_URL`。
- [ ] Render 已配置 `CORS_ORIGINS`。
- [ ] Render 未写入本机 Windows Tesseract 路径。
- [ ] Render 环境变量中没有把 `CORS_ORIGINS=` 前缀写进 value。

## 5. 文档检查

- [ ] README 完整。
- [ ] `docs/DEPLOYMENT.md` 完整。
- [ ] `docs/DEMO_SCRIPT.md` 完整。
- [ ] `docs/RESUME.md` 完整。
- [ ] `docs/INTERVIEW_QA.md` 完整。
- [ ] `docs/PROJECT_REVIEW.md` 完整。
- [ ] `docs/TESTING.md` 完整。
- [ ] `docs/EVALUATION.md` 完整。
- [ ] `docs/MCP_PLAN.md` 明确说明当前只是规划。
- [ ] `docs/SCREENSHOTS.md` 包含截图清单。

## 6. 简历检查

- [ ] 项目描述不过度夸大。
- [ ] 不写生产级系统。
- [ ] 不写真实用户量。
- [ ] 不写商业落地。
- [ ] 不暴露密钥。
- [ ] 能讲清楚自己负责什么。
- [ ] 能讲清楚为什么是 Agent。
- [ ] 能讲清楚为什么先做规则和工具，再接 LLM。
- [ ] 能讲清楚免费部署限制。

## 7. 发布前建议

- [ ] 补充真实截图到 `screenshots/`。
- [ ] 在 GitHub README 中确认图片链接存在后再插入。
- [ ] 重新打开公网前端和 Swagger。
- [ ] 用一个小 CSV、一个 PDF 和一张图片做完整演示。
- [ ] 检查浏览器控制台是否有报错。
- [ ] 检查 Render 日志是否有异常。
