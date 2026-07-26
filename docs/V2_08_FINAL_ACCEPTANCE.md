# V2-08 最终验收记录

## 验收环境说明

验收在完全隔离的独立目录中执行，不接触真实 `backend/.env`、真实数据库、真实用户文件或真实 API Key。

### 环境参数

| 项目 | 值 |
|------|-----|
| 隔离根目录 | `.runtime/final-acceptance/` |
| 数据库 | 独立 SQLite，存放于 `.runtime/final-acceptance/data/acceptance.db` |
| 认证密钥 | `AUTH_SECRET_KEY` 每次随机生成 64 字符，不写入仓库 |
| LLM | `LLM_ENABLED=false`，不调用 DeepSeek 或任何外部 API |
| Legacy V1 API | `ENABLE_LEGACY_V1_API=false` |
| 临时管理员 | `acceptance_admin`，密码随机 16 字符，仅当次会话有效 |
| 存储 | 独立 `storage/uploads/`、`storage/charts/`、`storage/reports/` |

### 验收脚本

| 脚本 | 用途 |
|------|------|
| `scripts/start_final_acceptance.ps1` | 创建隔离目录、生成随机密钥、运行 Alembic、创建管理员和邀请码、输出启动命令 |
| `scripts/stop_final_acceptance.ps1` | 优雅停止验收环境中的 uvicorn 和 worker 进程 |
| `scripts/clean_final_acceptance.ps1` | 删除 `.runtime/final-acceptance/` 全部内容（需输入 YES 确认） |

## 后端测试

### 执行命令

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m pytest --basetemp=../.runtime/pytest-final
```

### 结果

- **90 passed**，退出码 0
- **1708 warnings**（分类见下）
- 执行时间：约 29s（V2-07 阶段记录）
- 所有测试使用独立临时数据库，LLM/OCR 关闭，不读取真实 `.env`

### 警告来源分类

| 来源 | 数量（估算） | 性质 |
|------|-------------|------|
| Starlette `TestClient` 对 httpx 的弃用 | ~1600+ | 第三方库内部，不影响测试正确性 |
| Pandas `DeprecationWarning`（类型推断相关） | ~80 | DataFrame 操作提示，运行时无害 |
| `pkg_resources` 弃用提示 | ~15 | 来自 `pytesseract` 等依赖的内部导入 |
| 其他第三方库内部警告 | ~10 | 不影响验收结论 |

## 前端测试

### 执行命令

```powershell
cd D:\spir\NO2_agent\frontend
npm test
```

### 结果

- **10 passed**，纯逻辑测试，不依赖浏览器
- 覆盖范围：
  - 状态映射（`statusMeta`）：中文文案和非颜色语义
  - 错误映射（`mapApiError`）：标题、下一步和技术标识
  - 配额预警（`quotaState`）：80% 进入 warning，超限 danger
  - 计划校验（`validatePlanSteps`）：拒绝倒序依赖、要求审核最后执行
  - SSE 合并（`mergeEvents`）：按 ID 去重、新数据覆盖、限制长度
  - 报告排序（`sortReportVersions`）：当前版本优先，其余倒序
  - 文件类型映射（`fileTypeMeta`）：`.xlsx`、`pdf` 等
  - 权限导航（`allowedNavigation`）：普通用户 vs 管理员
  - 一次性秘密（`oneTimeSecretReducer`）：关闭后清除明文
  - 主题读取（`readThemePreference`）：非法值和异常回退 system

## Alembic 迁移测试

### 执行方式

使用独立临时 SQLite，覆盖完整迁移链路：

```powershell
cd D:\spir\NO2_agent\backend
$env:DATABASE_URL = "sqlite:///C:/path/to/temp.db"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade 20260724_0005
.\.venv\Scripts\alembic.exe upgrade head
```

### 结果

- **升级到 head**：成功，6 个 revisions 依次执行
  - `20260723_0001`：当前 schema 基线
  - `20260723_0002`：V2 身份和工作区
  - `20260723_0003`：认证安全
  - `20260723_0004`：文件理解
  - `20260724_0005`：可靠任务执行
  - `20260724_0006`：报告治理评估
- **回退 1 级**：`downgrade 20260724_0005`，成功
- **再升级**：`upgrade head`，成功回到 `20260724_0006`
- `alembic check`：`No new upgrade operations detected.`

注意：真实开发数据库当前 revision 为 `20260724_0005`，**未在本次验收中自动升级**。生产升级前需先备份并停写。

## Deterministic 评估

### 执行

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m app.evaluation.run_eval --mode deterministic --dataset v2-core
```

### 结果

- **总案例数**：85 条
- **task_success_rate**：1.0
- **分类分布**：table_analysis(15)、multi_table(10)、document_retrieval(15)、cross_source(10)、ocr(5)、clarification(10)、refusal(10)、report_integrity(10)
- **平均响应时间**：约 1ms
- **P95 响应时间**：约 1ms
- **平均模型调用**：0
- **平均工具调用**：1.65

### 重要说明

**这里的 `task_success_rate=1.0` 是确定性规则与预期路由的自检结果，不代表真实 Agent 或 DeepSeek 模型准确率。**

具体而言，`_deterministic_execute` 函数直接使用每条评估案例中预设的 `expected_agent_json`、`expected_tools_json`、`expected_citations_json` 和 `auto_checks_json` 作为"执行结果"，然后与自身比对。这种设计验证的是：

1. 评估集的预期路由逻辑自洽性（预期分类、预期 Agent、预期工具、预期引用是否正确填写）
2. `_score_case` 的评分逻辑不会错误标记合规案例为失败
3. 新引入的 Agent 分类或工具注册不会破坏现有案例的预期

它不能验证：

- DeepSeek 是否将某案例正确分类
- Agent 生成的报告质量
- OCR 真实识别准确率
- RAG 检索的召回和精确率

## Docker Compose 校验

```powershell
# 开发环境
cd D:\spir\NO2_agent
docker compose config --quiet

# 生产环境（需提供临时验证密钥）
docker compose --env-file deploy/.env.production -f docker-compose.prod.yml config --quiet
```

- dev Compose `config --quiet`：返回 0
- prod Compose `config --quiet`：在提供临时 `AUTH_SECRET_KEY` 后返回 0
- 仅出现当前用户 Docker 客户端配置不可读警告，不影响 Compose 配置解析

**未验证**：生产 Compose 的实际 `docker compose up` 容器启动和运行态。V2-07 验证期间，构建 prod backend/web 镜像时因 Docker Hub 基础镜像鉴权 token 的 IPv6 连接超时而失败。

## pip check / compileall

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\pip.exe check
.\.venv\Scripts\python.exe -m compileall -q app/
```

- **pip check**：无依赖冲突
- **compileall**：全部 `.py` 文件编译通过

## 前端构建

```powershell
cd D:\spir\NO2_agent\frontend
npm run build
```

- 77 modules transformed，构建成功
- `build.sourcemap: false`，生产产物无 source map
- 未检测到 `dangerouslySetInnerHTML`
- 未检测到 hardcoded URL（Vercel、Render、localhost 等）
- API 请求使用相对路径 `/api/v2/`

## Git 检查

```powershell
cd D:\spir\NO2_agent
git diff --check
```

- 返回 0，无空白错误
- 仅有 Git 的 LF/CRLF 工作区提示（Windows 环境正常现象）
- 无 `.env`、`.db`、`*.pem`、`*.key`、证书文件在跟踪或变更中

## 验收结论

### 已验收项

| 类别 | 项目 | 状态 | 证据 |
|------|------|------|------|
| 后端测试 | 90 passed | 通过 | pytest 退出码 0 |
| 前端测试 | 10 passed | 通过 | node:test 10/10 |
| Alembic 迁移 | upgrade → downgrade → upgrade | 通过 | 6 revisions 链路完整 |
| deterministic 评估 | 85 条 rule-based | 通过 | task_success_rate=1.0 |
| Docker Compose 语法 | dev 和 prod 均通过 | 通过 | config --quiet 返回 0 |
| pip check | 无冲突 | 通过 | exit 0 |
| compileall | 全部编译通过 | 通过 | exit 0 |
| 前端构建 | 77 modules, sourcemap=false | 通过 | npm run build 成功 |
| Git diff --check | 无空白错误 | 通过 | exit 0 |
| 弃用修复 | datetime.utcnow() 统一替换 | 通过 | grep 确认 |
| 无密钥泄露 | .env 等均排除 | 通过 | .gitignore + grep 确认 |

### 未验收项

| 类别 | 项目 | 原因 |
|------|------|------|
| 浏览器验收 | 所有页面的完整交互和视觉 | 需人工执行 V2-07_MANUAL_ACCEPTANCE.md |
| OCR 真实验收 | 中文图片识别准确率 | 需 Tesseract + 真实图片 |
| DeepSeek 真实验收 | 模型质量、延迟和成本 | 需真实 API Key 和国内网络 |
| 生产容器构建和启动 | prod compose up | 基础镜像 pull 因 IPv6 超时失败 |
| 国内网络测试 | 多运营商实际访问 | 未购买服务器、未配置公网 |
| HTTPS 证书 | 真实证书链验证 | 未购买域名、未申请证书 |
| 系统恢复演练 | 从备份完整恢复 | 需真实生产数据 |
| 前端 E2E | 浏览器自动化测试 | 未引入 Playwright 或同等工具 |
| 真实 Alembic 升级 | 现有开发数据库升级到 head | 需负责人备份后手动执行 |
