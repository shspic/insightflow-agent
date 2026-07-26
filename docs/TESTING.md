# 测试说明

## 1. 测试目标

本项目当前测试目标是保证核心工程结构可用、API 接口正确、Agent 工作流可靠、数据库迁移可来回滚动、前端可完成生产构建。测试覆盖轻量 smoke test、服务层单元测试、认证/权限/文件/任务/报告集成测试和 deterministic 评估。

## 2. 后端测试范围

后端测试位于 `backend/tests/`，共 17 个测试文件，90 条测试用例全部通过（`90 passed, 1708 warnings`）：

- `test_health.py`：验证 `/api/health` 返回 200。
- `test_config.py`：验证配置模块可导入，默认配置存在，测试环境不使用真实 API Key。
- `test_basic_services.py`：验证核心 service 模块可正确导入。
- `test_v2_database_models.py`：验证 V2 数据库模型定义和关系。
- `test_alembic_migrations.py`：验证 Alembic 迁移可升级、回退、再升级。
- `test_v2_auth.py`：验证注册、登录、退出、Session、CSRF、密码修改和强制改密。
- `test_v2_admin.py`：验证管理员 CLI 初始化、邀请码管理、密码重置、用户状态。
- `test_v2_workspaces.py`：验证工作区 CRUD、软删除/恢复、工作区级数据隔离。
- `test_v2_file_understanding.py`：验证五类文件解析、Profile、角色/标签建议。
- `test_v2_relations_context.py`：验证文件关系候选、确认/拒绝/修改、Workspace Context。
- `test_v2_file_api_security.py`：验证文件上传限制、类型校验、大小/数量配额和归属校验。
- `test_v2_task_state_machine.py`：验证任务状态机迁移合法性、非法迁移被阻止。
- `test_v2_task_execution.py`：验证数据库队列、Worker 领取、租约/心跳、步骤执行。
- `test_v2_multi_agent.py`：验证 Supervisor + 五个专业 Agent 编排和结构化状态传递。
- `test_v2_report_delivery.py`：验证报告版本、三模板、Markdown/DOCX/PDF 导出、反馈和重新生成。
- `test_v2_governance.py`：验证配额检查、模型调用记录、评估集执行、清理 dry-run/apply、备份/恢复。
- `test_v2_deployment.py`：验证生产配置门禁、占位符拒绝、旧模型降级 readiness、Nginx SSE/SPA、Docker Compose 配置。

运行方式：

```powershell
cd backend
pytest --basetemp=./pytest_tmp
```

说明：由于 Windows 系统临时目录清理权限问题，建议使用工作区 `--basetemp` 参数避免退出码误报。测试环境关闭真实 LLM/OCR，不读取真实 `.env`，不调用真实 DeepSeek API。12 条 Starlette TestClient 弃用警告保留不处理（来自第三方依赖）。

## 3. Alembic 数据库迁移测试

Alembic 迁移测试验证从零升级到 head、回退和再次升级的完整循环：

```powershell
cd backend
pytest tests/test_alembic_migrations.py -v
```

当前 head：`20260724_0006`。测试使用独立临时 SQLite，不影响真实开发数据库。真实开发数据库的 `current` revision 仍然是 `20260724_0005`，需负责人备份后手动升级。

## 4. deterministic 评估

85 条 deterministic 评估是**确定性规则自检**，不代表 DeepSeek 模型准确率。它验证系统的非 LLM 部分（文件类型判断、工具选择、角色推断规则、报告模板匹配）是否按设计工作。

运行方式：

```powershell
cd backend
python -m app.evaluation.runner --mode deterministic
```

当前结果：`task_success_rate=1.0`、平均响应 1ms、P95 1ms、平均模型调用 0、平均工具调用 1.65。评估不调用 DeepSeek，85 条全部命中说明确定性路由代码正确。

## 5. 前端测试

前端测试位于 `frontend/src/`，共 10 条纯逻辑测试全部通过（`10 passed`）：

覆盖范围：状态管理逻辑（任务状态、错误处理）、配额显示/计算逻辑、SSE 事件解析/去重/上限、计划步骤渲染/确认状态、报告版本/模板选择逻辑、权限/认证边界、CSRF Token 管理、主题切换逻辑。

运行方式：

```powershell
cd frontend
npm test
```

## 6. 前端生产构建测试

验证 Vite 生产构建是否正常完成：

```powershell
cd frontend
npm install
npm run build
```

当前结果：成功，`77 modules transformed`，无 source map（生产构建关闭了 source map），无编译警告。

## 7. Docker Compose 测试

开发环境 Compose：

```powershell
docker compose up --build
```

生产环境 Compose 配置校验：

```powershell
docker compose -f docker-compose.prod.yml config --quiet
```

当前结果：开发与生产 Compose 均 `config --quiet` 返回 0。隔离 smoke Compose 在缺少验证密钥时按预期返回 1。

## 8. 依赖与代码完整性检查

```powershell
cd backend
pip check
python -m compileall app
```

当前结果：`pip check` 无依赖冲突；`compileall` 全部通过。

## 9. localhost 地址说明

以下地址为本地开发专用，不对外提供服务：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- Swagger：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/api/health`

## 10. 手动验收清单

- `/api/health` 返回 `status: ok`。
- 注册（需邀请码）、登录、退出、修改密码流程正常。
- 工作区创建、文件上传、文件列表正常。
- CSV / Excel 解析多工作表、字段、行列数和预览数据正常。
- PDF 分页解析和文本提取正常。
- 图片 OCR 可执行（需 Tesseract 中英文语言包）。
- Markdown 文件解析正常。
- 文件关系候选展示证据和置信度，确认/拒绝/修改正常。
- 任务创建、追问、计划确认正常。
- SSE 实时进度展示正常，断线可恢复。
- 报告 Markdown/DOCX/PDF 下载正常。
- 管理员邀请码、密码重置、用户管理正常。
- Docker Compose 可启动前端和后端。
- 生产 Compose 配置校验通过。

## 11. 当前未覆盖的测试

- 尚未覆盖真实文件上传的端到端自动化测试（Playwright/E2E）。
- 尚未覆盖真实 DeepSeek 调用的质量评估（需公网部署后执行）。
- 尚未覆盖真实扫描 PDF 的 OCR 准确率评估。
- 尚未覆盖真实 DOCX/PDF 渲染的视觉回归测试。
- 尚未覆盖浏览器端 UI 自动化测试。
- 尚未覆盖多用户并发场景。
- 尚未配置 GitHub Actions CI/CD。

## 12. 后续测试增强方向

- 增加 Playwright 前端核心流程 E2E 测试。
- 增加真实 DeepSeek 调用的评估集和端到端回归。
- 增加真实扫描 PDF OCR 样例和识别准确率记录。
- 增加 DOCX/PDF 渲染视觉回归（需 LibreOffice/Poppler 环境）。
- 增加多用户并发隔离测试。
- 增加 GitHub Actions 自动运行后端测试、前端测试和构建。
- 增加代码覆盖率报告。
