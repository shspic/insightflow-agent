# V2-03 手动验收清单

## 1. 准备

不要使用真实用户数据库做破坏性验收。推荐复制配置并使用独立 SQLite：

```powershell
cd D:\spir\NO2_agent\backend
$env:DATABASE_URL="sqlite:///./data/v2-03-acceptance.db"
$env:ALEMBIC_DATABASE_URL="sqlite:///./data/v2-03-acceptance.db"
$env:LLM_ENABLED="false"
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m app.cli.create_admin
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

另一个终端：

```powershell
cd D:\spir\NO2_agent\frontend
npm run dev
```

访问 `http://localhost:5173`。

## 2. 管理员和注册

1. 使用初始化管理员登录。
2. 创建一个可使用 2 次的邀请码。
3. 注册普通用户 A。
4. 使用同一邀请码注册普通用户 B。
5. 确认登录、退出、CSRF 和工作区页面仍正常。

## 3. 工作区与批量上传

1. 用户 A 创建工作区“V2-03 验收”。
2. 一次选择 CSV、XLSX、文本 PDF、图片、Markdown。
3. 确认每个文件显示名称、类型、大小和上传状态。
4. 验证 `.exe` 返回不支持类型。
5. 将文本内容改名为 `.pdf`，确认内容校验失败。
6. 上传超过 `UPLOAD_MAX_FILE_SIZE_BYTES` 的文件，确认提示文件过大。
7. 上传超过 `UPLOAD_MAX_BATCH_FILES` 的文件，确认提示批量超限。
8. 临时调低用户配额，确认普通用户收到配额不足；管理员仍受单文件安全上限。

## 4. 文件理解

1. 选择全部文件，点击“批量理解”。
2. CSV：核对行列、字段、缺失、重复、数值和日期信息。
3. XLSX：核对所有工作表都出现，不只显示第一个。
4. PDF：核对页数、文本长度、标题候选和 chunk。
5. 扫描 PDF：核对出现需要 OCR 的降级提示，不伪造摘要。
6. 图片：有 Tesseract 时核对 OCR 摘要；无 Tesseract 时核对基础 Profile 仍存在。
7. Markdown：核对标题层级、代码块、表格和链接数量。
8. 确认页面没有执行 Markdown 代码、HTML 或外部链接。
9. 点击“重新理解”，确认 Profile 版本增加。

## 5. 角色和标签

1. 确认系统推荐角色。
2. 修改为另一个内置角色。
3. 修改为合法自定义角色。
4. 输入重复标签，确认保存后去重。
5. 输入控制字符或尖括号标签，确认不会作为有效标签保存。
6. 再次运行理解，确认用户角色不被系统建议覆盖。

## 6. 文件关系

1. 上传字段高度重合的两个 CSV/XLSX。
2. 上传包含表格指标/规则的 PDF 或 Markdown。
3. 上传 OCR 文本与上述资料明显重合的图片。
4. 点击“生成关系候选”。
5. 核对关系类型、置信度和简短证据。
6. 确认一个关系。
7. 拒绝一个关系。
8. 修改一个关系类型并填写备注。
9. 重新生成候选，确认不会无限重复，用户决定不被覆盖。
10. 从工作区移除某文件，确认相关关系不再可访问。

## 7. Workspace Context

1. 选择部分文件并生成预览。
2. 确认只包含选中文件。
3. 确认角色优先使用用户确认值。
4. 确认包含已确认关系和高置信待确认关系。
5. 确认包含质量问题、未就绪文件和工具能力。
6. 确认显示 `context_version=2.03`。
7. 确认不含绝对路径、密码、Token、Session、API Key 或完整原文。
8. 临时调低 Context 限制，确认出现裁剪提示和省略文件 ID。

## 8. 双用户隔离

1. 用户 B 创建另一个工作区并上传文件。
2. 使用浏览器开发工具尝试把用户 B 的 workspace/file/relation ID 放入用户 A 请求。
3. 单文件理解、Profile、关系、Context 和下载均应返回 404 或安全的范围错误。
4. 管理员使用普通工作区能力也不能读取 A/B 的工作区内容。

## 9. 错误体验

逐项确认页面能区分：

- 文件不支持；
- 文件过大；
- 批量或配额超限；
- 内容/MIME 校验失败；
- 解析失败；
- OCR 不可用；
- DeepSeek 不可用并降级；
- Session 失效；
- 无权限；
- 服务器错误。

生产环境外只在开发控制台保留技术响应；页面不应统一显示
`Failed to fetch`。

## 10. 自动验证

```powershell
cd D:\spir\NO2_agent\backend
pytest
alembic heads
alembic current
```

临时库往返：

```powershell
$env:ALEMBIC_DATABASE_URL="sqlite:///./data/v2-03-roundtrip.db"
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
.\.venv\Scripts\alembic.exe -c alembic.ini downgrade 20260723_0003
.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
```

前端：

```powershell
cd D:\spir\NO2_agent\frontend
npm run build
```

仓库：

```powershell
cd D:\spir\NO2_agent
git diff --check
git status --short
```

验收结束后不要把临时数据库、上传文件、`.env` 或密钥提交到仓库。
