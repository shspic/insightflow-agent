# 测试说明

## 1. 测试目标

本项目当前测试目标是保证核心工程结构可用、API 接口正确、Agent 工作流可靠、数据库迁移可来回滚动、前端可完成生产构建。测试覆盖轻量 smoke test、服务层单元测试、认证/权限/文件/任务/报告集成测试、工程审查契约专项和 deterministic 评估。

## 2. 后端测试范围

后端测试位于 `backend/tests/`，当前共 44 个 `test_*.py` 文件。2026-08-11 静态收集为 **959 tests**，Alembic 迁移专项仍为 **16 tests**。最近文档化的完整成功基线是 Stage 6C 的 **791 passed**；本轮关闭真实 LLM、使用 FakeEmbedding 的全量隔离重跑超过 300 秒未完成，因此当前只能写“959 collected”，不能写“959 passed”。

- V2 主线：健康检查、配置、数据库模型、认证、管理员、工作区、文件理解、关系上下文、文件安全、任务状态机、任务执行、多 Agent、报告交付、治理、部署、存储隔离；
- V3 主线：检索基线（4A）、稠密混合检索（4B）、真实 API 集成（4C1）、LLM 契约（4C2）、Verification Agent（4C2）、候选决策（4C3）、工程检索 API（4C）、MCP 工具（5A1）、Verification MCP 集成（5A2）、DeepSeek 脚本契约（5B）、Supervisor 与质量门（5B）、Supervisor API（5B）、阶段 6A 端到端评测、6A 契约专项（Evidence 来源完整性 / input snapshot / validation split）。

- `test_health.py`：验证 `/api/health` 返回 200。
- `test_config.py`：验证配置模块可导入，默认配置存在，测试环境不使用真实 API Key。
- `test_basic_services.py`：验证核心 service 模块可正确导入。
- `test_v2_database_models.py`：验证 V2 数据库模型定义和关系。
- `test_alembic_migrations.py`：验证 Alembic 迁移可升级、回退、再升级。
- `test_v2_auth.py`：验证注册、登录、退出、Session、CSRF、密码修改和强制改密。
- `test_v2_admin.py`：验证管理员 CLI 初始化、邀请码管理、密码重置、用户状态。
- `test_v2_workspaces.py`：验证工作区 CRUD、永久删除、归档、工作区级数据隔离。
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

当前代码 head：`20260812_0014`（2026-08-11 通过 `alembic heads` 核验）。测试使用独立临时 SQLite，不影响真实开发或公网数据库；公网匿名健康接口不公开具体 revision，线上 current 必须通过受控服务器命令或发布记录核验，不能从本地 head 推断。

## 4. deterministic 评估

85 条 deterministic 评估是**确定性规则自检**，不代表 DeepSeek 模型准确率。它验证系统的非 LLM 部分（文件类型判断、工具选择、角色推断规则、报告模板匹配）是否按设计工作。

运行方式：

```powershell
cd backend
python -m app.evaluation.runner --mode deterministic
```

当前结果：`task_success_rate=1.0`、平均响应 1ms、P95 1ms、平均模型调用 0、平均工具调用 1.65。评估不调用 DeepSeek，85 条全部命中说明确定性路由代码正确。

## 5. 前端测试

前端测试位于 `frontend/src/`。2026-08-11 实际执行结果为 **116 passed，0 failed**：

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

当前结果：2026-08-11 构建成功，`92 modules transformed`，无 source map（生产构建关闭了 source map），无编译警告。

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

## 11. 当前未覆盖或未完成的测试

- 已有 Stage 6A 真实 DeepSeek+BGE+MCP 评测，不再属于未覆盖项；但 validation recall@3=0.6429、no-answer FP 率=1.0，不能表述为业务准确率已经达标。
- 已配置 GitHub Actions 和 Playwright；Stage 6B/6C 已有历史浏览器通过记录。2026-08-11 对公网 Stage 6D-2 实测为 `7 passed, 1 failed`，失败原因是页脚缺少“公安联网备案办理中”占位。
- 尚未覆盖从公网真实文件上传到工程审查、MCP、Supervisor、报告下载的版本化登录后全链自动化验收。
- 尚未覆盖真实扫描 PDF 的 OCR 准确率评估和 DOCX/PDF 渲染的完整视觉回归。
- 尚未覆盖多用户高频并发、SQLite 压力上限、高可用与故障切换。
- 当前后端可收集 959 项，但本轮全量运行未在 300 秒内完成；获得新的完整成功记录前，不更新为“959 全部通过”。

## 12. 后续测试增强方向

- 扩展 Playwright 到公网登录后的文件上传、工程审查、MCP、Supervisor 和报告下载完整链路。
- 扩充真实 DeepSeek+BGE 评估集，重点降低 no-answer 误召回并提升 validation recall@3。
- 增加真实扫描 PDF OCR 样例和识别准确率记录。
- 增加 DOCX/PDF 渲染视觉回归（需 LibreOffice/Poppler 环境）。
- 增加多用户并发、SQLite 压力上限和故障恢复测试。
- 在 CI 中持续记录当前完整 pytest 的通过/失败/跳过数量和耗时，避免只维护 collected 数量。
- 增加代码覆盖率报告。
