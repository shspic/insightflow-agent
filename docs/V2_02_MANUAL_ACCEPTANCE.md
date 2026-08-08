# V2-02 手动验收清单

## 1. 验收前准备

1. 备份真实数据库，不在验收中删除 `app.db`。
2. 配置本地 `backend/.env` 的高熵 `AUTH_SECRET_KEY`。
3. 确认本地为 `ENV=development`、`AUTH_COOKIE_SECURE=false`。
4. 新数据库执行 `alembic upgrade head`；已有库按迁移文档先确认 revision。
5. 分别启动 FastAPI 和 Vite，浏览器访问 `http://localhost:5173`，不要直接使用跨域后端地址。

## 2. 管理员初始化与邀请码

```powershell
cd D:\spir\NO2_agent\backend
.\.venv\Scripts\python.exe -m app.cli.create_admin
```

- [ ] 密码输入不回显。
- [ ] 不存在默认 `admin/admin`。
- [ ] 管理员可以用账号和密码登录，登录页没有邀请码输入框。
- [ ] 管理员后台可创建邀请码。
- [ ] 完整邀请码只在创建结果显示一次；关闭提示后列表只显示 hint。
- [ ] 轮换后显示一次新邀请码，旧邀请码无法注册。

## 3. 注册、登录和工作区

- [ ] 注册页要求账号、密码、确认密码、邀请码。
- [ ] 错误、过期、耗尽或停用邀请码不能注册。
- [ ] 有效邀请码可注册普通用户，使用次数增加。
- [ ] 普通用户登录后进入工作区列表。
- [ ] 可创建、改名、归档、恢复使用和永久删除工作区（需完整名称确认）。
- [ ] 刷新页面后通过 `/auth/me` 恢复登录状态。
- [ ] 浏览器 localStorage 和 sessionStorage 中不存在 Session Token。

## 4. 文件与任务

- [ ] 在工作区详情上传 CSV/XLSX/PDF/图片。
- [ ] 文件列表可解析；表格可分析/生成图表，PDF 可索引，图片可 OCR。
- [ ] 网络响应中没有 `file_path`、`storage_path` 或服务器绝对路径。
- [ ] 可选择当前工作区文件并提交同步任务。
- [ ] 可查看任务结果、历史、执行轨迹和 Markdown 报告。
- [ ] 报告响应中没有 `report_path`，下载仍可用。
- [ ] 另一个普通用户猜测工作区、文件、任务或下载 ID 时均得到 404。
- [ ] 管理员也不能直接打开普通用户文件 URL。

## 5. 密码重置

- [ ] 未登录用户提交存在和不存在账号时都看到：“申请已提交。如账号存在，管理员将进行处理。”
- [ ] 管理员能看到 pending 申请并拒绝。
- [ ] 管理员生成临时密码时只显示一次。
- [ ] 刷新或关闭提示后不能再次查询该明文。
- [ ] 原密码和旧 Session 立即失效。
- [ ] 用户用临时密码登录后被强制跳转 `/change-password`。
- [ ] 强制改密状态只能访问当前用户、退出和修改密码接口。
- [ ] 修改成功后进入工作区，旧 Session 全部失效，申请状态为 completed。

## 6. 用户与审计

- [ ] 普通用户无法进入 `/admin` 或调用管理员 API。
- [ ] 管理员可禁用/启用普通用户，不能禁用自己。
- [ ] 被禁用用户不能登录，已有 Session 失效。
- [ ] 用户列表不显示密码、Session 或文件内容。
- [ ] 审计列表不显示真实 IP、密码、完整邀请码、Token、临时密码或 API Key。

## 7. Legacy 和旧数据

- [ ] `ENABLE_LEGACY_V1_API=false` 时旧文件、任务、报告接口不可用。
- [ ] 旧数据认领不带 `--apply` 时只打印数量，不写数据库。
- [ ] 显式认领后 owner 为空的文件和任务进入目标用户的“旧版数据”工作区。
- [ ] 重复认领不创建重复关联。

## 8. 自动验证命令

```powershell
cd D:\spir\NO2_agent\backend
pytest
alembic heads
alembic current
```

迁移往返必须使用临时数据库：

```powershell
$env:ALEMBIC_DATABASE_URL = "sqlite:///D:/temporary/insightflow-v2-02-test.db"
alembic upgrade head
alembic downgrade 20260723_0002
alembic upgrade head
Remove-Item Env:ALEMBIC_DATABASE_URL
```

前端和 Git：

```powershell
cd D:\spir\NO2_agent\frontend
npm run build
cd D:\spir\NO2_agent
git diff --check
git status --short
```

不要把示例临时路径指向真实 `backend/data/app.db`。
