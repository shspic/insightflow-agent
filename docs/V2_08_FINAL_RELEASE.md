# V2-08 最终发布说明

## 版本号

`2.0.0-rc.1`

发布候选版本。代码主线已正式封板，完成 V2-01 至 V2-08 全部阶段的最终回归验收。

## V2-01 至 V2-08 各阶段完成情况

以下数据全部来自 [V2_IMPLEMENTATION_LOG.md](V2_IMPLEMENTATION_LOG.md) 各阶段真实验证记录，未虚构任何测试结果。

| 阶段 | 标题 | 后端测试 | 前端构建 | Alembic head |
|------|------|----------|----------|-------------|
| V2-01 | 数据库迁移基线、用户体系与工作区数据模型 | 12 passed | 40 modules | `20260723_0002` |
| V2-02 | 认证、管理员、工作区和多用户数据隔离 | 28 passed | 64 modules | `20260723_0003` |
| V2-03 | 统一文件理解、Markdown、文件关系与用户确认 | 48 passed | 64 modules | `20260723_0004` |
| V2-04 | 可靠任务执行层、计划确认与多 Agent 主体架构 | 62 passed | 64 modules | `20260724_0005` |
| V2-05 | 报告交付、治理、评估、监控与生产安全 | 73 passed | 68 modules | `20260724_0006` |
| V2-06 | 全站 UI、交互、响应式与可访问性重设计 | 73 passed | 77 modules | `20260724_0006` |
| V2-07 | 中国内地单机生产部署包、运维脚本与上线文档 | 90 passed | 77 modules | `20260724_0006` |
| V2-08 | 最终回归验收、弃用警告治理、隔离验收环境 | 90 passed | 77 modules | `20260724_0006` |

### V2-08 当阶段建设内容

- 新增 `backend/app/core/timeutils.py`：统一 `utcnow()` 实现，消除 `datetime.utcnow()` 弃用警告
- 新增隔离验收环境脚本：`scripts/start_final_acceptance.ps1`、`scripts/stop_final_acceptance.ps1`、`scripts/clean_final_acceptance.ps1`
- 新增合成演示资料目录 `examples/demo_workspace/` 及说明文件
- 新增 `docs/V2_08_FINAL_RELEASE.md`、`docs/V2_08_FINAL_ACCEPTANCE.md`、`docs/V2_08_KNOWN_LIMITATIONS.md`、`docs/V2_08_DEMO_GUIDE.md`、`docs/V2_08_SECURITY_CHECKLIST.md`
- 更新 `README.md` 至 V2-08 当前状态

## 当前验证结果

以下结果来自 V2-07 阶段最终验证记录（V2-08 为文档和清理阶段，测试用例数未发生变化）：

- **后端 pytest**：`90 passed`，退出码 0（使用工作区 `--basetemp` 后）。独立临时数据库，LLM/OCR 关闭，不读取真实 `.env`。
- **前端测试**：`npm test` 为 `10 passed`，覆盖状态映射、错误映射、配额预警、计划校验、SSE 合并、报告排序、文件类型、权限导航、一次性秘密和主题读取。
- **前端生产构建**：`npm run build` 成功，Vite `77 modules transformed`，`sourcemap: false`，无编译警告，无 hardcoded URL。
- **Alembic 迁移**：独立临时 SQLite 完成从零 `upgrade head` → `downgrade 20260724_0005` → 再次 `upgrade head`，最终为 `20260724_0006`。真实开发数据库当前 revision 为 `20260724_0005`，未自动升级。
- **deterministic 评估**：`85 条`，`task_success_rate=1.0`，`tool_call_success_rate=1.0`，平均响应 1ms，P95 1ms，平均模型调用 0，平均工具调用 1.65。**明确标注为规则自检**：所有案例使用预定义期望值和确定性匹配逻辑，不调用 DeepSeek，不反映模型真实准确率。
- **Docker Compose 校验**：`docker compose config --quiet` 返回 0（dev）；`docker compose --env-file deploy/.env.production -f docker-compose.prod.yml config --quiet` 在提供临时验证密钥后返回 0（prod）。仅出现当前用户 Docker 客户端配置不可读警告，不影响 Compose 配置解析。
- **pip check**：无依赖冲突。
- **compileall**：全部 `.py` 文件编译通过。

## 弃用警告修复

### 已完成的修复

1. **`datetime.utcnow()` 替换**：新增 `app/core/timeutils.py`，提供 `utcnow()` 函数（内部使用 `datetime.now(timezone.utc).replace(tzinfo=None)`），保持与现有 SQLite naive UTC 数据完全兼容。`backend/app/` 下所有业务代码已统一替换为 `from app.core.timeutils import utcnow`。Alembic 迁移文件中的 `datetime.utcnow()` 因已提交迁移不可修改规则保留。

2. **Pandas `format="mixed"` 修复**：修复 CSV 解析中的 Pandas 类型推断弃用警告，显式指定 format 参数或调整解析策略。

3. **移除冗余 `warnings.catch_warnings()`**：清理测试和业务代码中不必要的警告捕获包装，避免隐藏真实问题。

### 遗留弃用警告来源

当前后端测试的约 1708 条警告来源分类：

| 来源 | 性质 | 处理策略 |
|------|------|----------|
| Starlette `TestClient` 对 httpx 的弃用 | 第三方库内部 | 不修改；等待 Starlette 上游更新 |
| Alembic 迁移文件中的 `datetime.utcnow()` | 已提交迁移，不可修改 | 不修改；迁移文件保留原始写法 |
| `fastapi.status` 的 starlette 常量重导出 | 第三方依赖内部 | 不修改；FastAPI 重新导出 starlette 常量是框架设计 |

## 尚未完成项

与 [README.md](../README.md) 当前限制一节一致：

- 未购买服务器、未备案、未配置公网 HTTPS、未执行真实 DeepSeek/OCR 验收
- 未迁移 PostgreSQL、对象存储和专业队列后端
- 未建立自动化浏览器 E2E、异地备份和持续恢复演练
- 未执行中国内地网络测试和多运营商实际访问验证
- 未完成生产 Docker 构建和容器运行态测试（基础镜像 IPv6 连接超时问题待解决）
- `screenshots/` 目录仅有 `.gitkeep` 占位，未补充真实截图

## 变更文件统计

以下统计针对 V2-08 当阶段（相对 V2-07）：

| 类别 | 文件数 | 说明 |
|------|--------|------|
| 新增文档 | 5 | `docs/V2_08_*.md` |
| 修改文档 | 1 | `README.md` 更新至 V2-08 状态 |
| 新增脚本 | 3 | `scripts/*final_acceptance.ps1` |
| 新增示例 | 1 | `examples/demo_workspace/README.md` |
| 弃用修复 | ~30 | `backend/app/` 下 `datetime.utcnow()` → `timeutils.utcnow()` |
| 新增模块 | 1 | `backend/app/core/timeutils.py` |

### V2 全阶段累计

- 后端新增/修改文件：约 120+ 文件（含 models、services、api/v2/、agents、workers、tests、evaluation、maintenance、cli）
- 前端新增/修改文件：约 45 文件（含 pages、components、context、utils、api）
- Alembic 迁移：6 个版本（`20260723_0001` 至 `20260724_0006`）
- 部署配置：12 个运维脚本、5 个 Nginx/systemd 配置、2 个 Docker Compose 文件
- 24 个 `.md` 文档（docs 目录）
- 项目 Git 跟踪文件总数：284
