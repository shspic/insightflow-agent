# Stage 6B 真实浏览器验收证据

本目录记录 InsightFlow V3 Stage 6B 在隔离环境中的真实 Chrome 浏览器验收结果。验收日期为 2026-08-09，自动化框架为官方 `@playwright/test` 1.62.1，浏览器项目使用本机 Chrome。

## 已验证的关键用户旅程

1. 注册、登录并进入 engineering 工作区。
2. 创建工程项目，上传五份黄金材料并完成理解与人工角色确认（5/5）。
3. 创建并确认 ReviewBrief，执行 ReviewRun，得到 12 条 Finding 和正式 Evidence。
4. 启动 Supervisor，验证 extraction、verification、quality_review、reporting 四节点及 Quality Gate。
5. 验证检索索引缺失后的 prepare → retry 成功轨迹，并查看候选证据。
6. 人工接受一条候选、拒绝一条候选，刷新后决定仍然存在。
7. 生成报告 v1、v2、v3；接受候选后重新下载 v1，Markdown/PDF SHA-256 均保持不变。
8. 对 Finding 分别执行确认、驳回和修改，并在 v3 报告中核对统计结果。
9. 使用第二个正常用户直接访问第一个用户的项目，服务端返回统一的“不存在”页面。
10. 在 390×844 移动视口验证项目概览和智能核验页无整页横向溢出。

## 浏览器验收中发现并修复的问题

- `VerificationPanel` 缺少 `fetchSupervisorRun` 导入，导致 Supervisor 详情在真实页面中加载失败。
- 智能核验的直接子项缺少收缩约束，390px 视口出现整页横向溢出；修复后 `scrollWidth == clientWidth == 390`。
- 空项目尚未创建 ReviewBrief 时，current Brief 的预期 404 不再输出统一开发错误日志；真实业务错误仍按原逻辑展示。

## 报告不可变性证据

候选证据被接受并生成 v2 后，再次下载 v1，哈希与接受前一致：

- v1 Markdown：`BA9A9CA6B1A412433A030B04C9C95CAD8A1F228A955E7A345C68E717A1008CF2`
- v1 PDF：`3935023C01E3414987DD560EBF46EBE1E9D2E2399C513169BE937501458142F1`

## 截图索引

| 文件 | 内容 |
|---|---|
| `01-engineering-list.png` | 工程项目列表 |
| `02-materials-five-roles.png` | 五份材料与 5/5 角色确认 |
| `03-brief-confirmed.png` | 已确认 ReviewBrief |
| `04-review-completed.png` | ReviewRun 完成 |
| `05-supervisor-completed.png` | Supervisor 四节点与质量门 |
| `06-report-assets.png` | 报告资产下载入口 |
| `07-candidate-decisions.png` | 候选接受与拒绝结果 |
| `08-report-v2-and-v1.png` | v1/v2 版本并存 |
| `09-cross-user-denied.png` | 跨用户访问被拒绝 |
| `10-finding-actions.png` | Finding 人工操作结果 |
| `11-report-v3-actions.png` | v3 报告与操作统计 |
| `12-mobile-project-overview.png` | 390px 项目概览 |
| `13-mobile-verification-fixed.png` | 390px 智能核验修复后页面 |

## 可重复运行

`frontend/e2e/stage6b-live.spec.js` 面向已准备好的隔离黄金项目，要求通过环境变量提供前端地址、两个测试用户和项目 ID。示例：

```powershell
$env:STAGE6B_BASE_URL = "http://127.0.0.1:15186"
$env:STAGE6B_USERNAME = "<primary-user>"
$env:STAGE6B_PASSWORD = "<primary-password>"
$env:STAGE6B_SECONDARY_USERNAME = "<secondary-user>"
$env:STAGE6B_SECONDARY_PASSWORD = "<secondary-password>"
$env:STAGE6B_PROJECT_ID = "<project-id>"
npm run test:e2e:stage6b
```

测试账号、口令、临时数据库和运行时存储均不进入仓库。

## 边界说明

- Playwright 覆盖真实前后端联调和浏览器 UI，不把源码静态检查冒充浏览器测试。
- 浏览器流程真实展示了检索工具的 INDEX_MISSING → prepare → retry 链。
- MCP 瞬时失败的局部重试由 `scripts/verify_stage6a_retry_evaluation.py` 通过真实 Streamable HTTP MCP 独立验证；本目录不声称该故障是在浏览器内注入。
- 本次是本地隔离环境验收，不代表生产部署或公网环境验收。
