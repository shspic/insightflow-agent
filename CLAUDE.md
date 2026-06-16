# AGENTS.md



这个文件是写给 AI 编程助手看的，比如 Codex、Claude Code、Cursor Agent 等。



它的作用是告诉 AI：



1\. 这个项目是什么；

2\. 用什么技术；

3\. 应该怎么改代码；

4\. 哪些事情绝对不能做；

5\. 每次改完代码要怎么说明；

6\. 怎么避免乱改、误删、过度设计。



\---



\## 一、项目是什么



项目名称：InsightFlow Agent



这是一个“多模态文档与数据分析智能体”。



它不是普通聊天机器人。



它要做的是：



用户上传 Excel、CSV、PDF、图片等文件，然后用自然语言提出任务，比如：



\* 帮我分析这个 Excel；

\* 帮我总结这个 PDF；

\* 帮我识别这张图片里的内容；

\* 帮我生成图表；

\* 帮我根据这些资料生成分析报告。



系统收到任务后，要自动：



1\. 判断任务类型；

2\. 读取相关文件；

3\. 选择合适工具；

4\. 执行数据分析、文档检索、图片识别等操作；

5\. 生成图表或报告；

6\. 展示 Agent 每一步做了什么。



所以这个项目的核心不是“聊天”，而是“任务执行”。



\---



\## 二、项目要体现哪些能力



这个项目要体现：



1\. AI Agent 工作流；

2\. 工具调用；

3\. RAG 文档检索；

4\. 多模态文件处理；

5\. Pandas 数据分析；

6\. FastAPI 后端开发；

7\. React 前端开发；

8\. SQLite 保存任务历史；

9\. Agent 执行轨迹展示；

10\. Docker 部署；

11\. 低成本公网演示。



这些能力都是为了让项目可以写进简历，而不是只做一个 Demo。



\---



\## 三、技术栈



后端：



\* Python

\* FastAPI

\* Uvicorn

\* SQLite

\* SQLAlchemy

\* Pandas

\* openpyxl

\* PyMuPDF

\* Matplotlib

\* LangChain

\* LangGraph

\* Chroma 或 FAISS

\* python-dotenv

\* pytest



前端：



\* React

\* Vite

\* Axios

\* React Router

\* Markdown 渲染器

\* 可选图表库：Recharts 或 ECharts



部署：



\* Docker

\* Docker Compose

\* GitHub

\* Vercel 部署前端

\* Render 或其他低成本平台部署后端



\---



\## 四、强制语言规则



AI 编程助手和你交流时，必须使用简体中文。



包括：



1\. 回复；

2\. 计划；

3\. 总结；

4\. 问题说明；

5\. 代码注释；

6\. 修改说明。



但是下面这些可以保留英文：



1\. 代码关键字；

2\. 命令；

3\. 文件名；

4\. 路径；

5\. 接口名；

6\. 依赖名；

7\. 已有日志；

8\. 报错信息；

9\. 配置项。



例如：



```bash

uvicorn app.main:app --reload

```



这种命令不用翻译。



\---



\## 五、写代码前必须先理解



AI 不允许一上来就改代码。



改代码前必须先：



1\. 读取相关文件；

2\. 看懂现有项目结构；

3\. 看懂已有代码风格；

4\. 说明自己的关键假设；

5\. 如果需求不清楚，要先问；

6\. 如果有更简单的方案，要说明；

7\. 如果需求有风险，要提醒。



目的：避免 AI 自己脑补，然后乱改。



\---



\## 六、简单优先



AI 写代码时，只做当前任务需要的最小实现。



不允许：



1\. 用户没要求的功能自己加；

2\. 为一次性功能搞复杂抽象；

3\. 加一堆没必要的配置项；

4\. 为小概率情况写复杂逻辑；

5\. 随便增加新依赖；

6\. 把简单功能写复杂。



判断标准：



> 每一段新增代码，都必须直接服务于当前需求。



\---



\## 七、只做外科手术式修改



AI 只能改必须改的地方。



不允许：



1\. 顺手重构无关代码；

2\. 顺手格式化无关文件；

3\. 顺手改变量名；

4\. 顺手移动文件；

5\. 顺手删除旧代码；

6\. 顺手美化项目结构。



如果 AI 发现无关问题，只能在回复里提醒，不要主动改。



如果项目里有用户未提交的改动，AI 必须把它当成用户的工作成果，不能覆盖、回滚、格式化。



\---



\## 八、删除文件安全规则



AI 不能批量删除文件。



禁止使用：



```text

rm -rf

del /s

rd /s

rmdir /s

Remove-Item -Recurse

```



如果确实需要删除文件，只能一次删除一个明确路径的文件。



例如：



```powershell

Remove-Item "C:\\path\\to\\specific-file.txt"

```



如果 AI 不能明确说出要删除的完整路径，就不能删除。



\---



\## 九、目标驱动执行



AI 不能只说“修复问题”，必须把任务变成可验证目标。



例如：



“修复上传失败问题”应该变成：



1\. 先复现上传失败；

2\. 找到失败原因；

3\. 做最小修改；

4\. 再次测试上传；

5\. 说明验证结果。



如果是多步骤任务，AI 应该先给短计划。



\---



\## 十、命令和工具使用规则



AI 执行命令前必须知道目的。



要求：



1\. 先读代码，再改代码；

2\. 先搜索，再判断；

3\. 不运行会造成大范围改动的命令；

4\. 不随便安装依赖；

5\. 不随便升级依赖；

6\. 不随便修改 lock 文件；

7\. 不启动长期后台进程，除非任务需要。



如果启动了后端或前端，要告诉你怎么访问、怎么停止。



\---



\## 十一、本项目的特殊规则



因为这个项目是简历项目，所以要注意工程结构。



要求：



1\. 后端代码要模块化；

2\. 不要把所有逻辑都写在接口函数里；

3\. 尽量使用 service 层；

4\. API 按功能拆分；

5\. 不要把 API Key 写死；

6\. 不要提交 `.env`；

7\. 不要随便删除已有接口；

8\. 不要未经确认引入付费服务；

9\. 不允许执行用户输入的任意 Python 代码；

10\. 数据分析只能通过预设的 Pandas 工具函数完成；

11\. 文件上传要限制类型和大小；

12\. 图表和报告要保存到指定目录；

13\. 新增 API 后要更新 README 或接口说明；

14\. 重要后端函数尽量加简单测试；

15\. 每次改动尽量小。



\---



\## 十二、后端运行命令



创建虚拟环境：



```bash

cd backend

python -m venv .venv

```



Windows 激活虚拟环境：



```bash

.venv\\Scripts\\activate

```



安装依赖：



```bash

pip install -r requirements.txt

```



启动后端：



```bash

uvicorn app.main:app --reload

```



健康检查接口：



```text

GET /api/health

```



正常返回：



```json

{

&#x20; "status": "ok"

}

```



\---



\## 十三、前端运行命令



安装依赖：



```bash

cd frontend

npm install

```



启动前端：



```bash

npm run dev

```



默认访问地址：



```text

http://localhost:5173

```



\---



\## 十四、推荐开发顺序



这个项目不要一口气全做。



推荐顺序：



1\. 项目骨架；

2\. FastAPI 健康检查；

3\. SQLite 和 SQLAlchemy；

4\. 文件上传；

5\. 文件列表和详情；

6\. Excel / CSV 解析；

7\. PDF 文本提取；

8\. 图片上传；

9\. Pandas 数据概况分析；

10\. 图表生成；

11\. 任务创建接口；

12\. Agent 初版；

13\. 工具调用日志；

14\. Agent 执行轨迹接口；

15\. 前端上传页面；

16\. 前端任务工作区；

17\. 前端执行轨迹展示；

18\. LangGraph 工作流；

19\. PDF RAG；

20\. 图片 OCR；

21\. Markdown 报告生成；

22\. 报告下载；

23\. Docker Compose；

24\. 部署上线；

25\. 可选 MCP 工具服务。



\---



\## 十五、后端目录建议



```text

backend/

&#x20; app/

&#x20;   main.py

&#x20;   core/

&#x20;     config.py

&#x20;   api/

&#x20;     health.py

&#x20;     files.py

&#x20;     tasks.py

&#x20;     reports.py

&#x20;   models/

&#x20;     file.py

&#x20;     task.py

&#x20;     tool\_call.py

&#x20;   schemas/

&#x20;     file.py

&#x20;     task.py

&#x20;     report.py

&#x20;   services/

&#x20;     file\_service.py

&#x20;     parser\_service.py

&#x20;     analysis\_service.py

&#x20;     chart\_service.py

&#x20;     report\_service.py

&#x20;     rag\_service.py

&#x20;     agent\_service.py

&#x20;   agents/

&#x20;     state.py

&#x20;     graph.py

&#x20;     nodes.py

&#x20;     tools.py

&#x20;     prompts.py

&#x20;   db/

&#x20;     session.py

&#x20;     init\_db.py

&#x20;   storage/

&#x20;     uploads/

&#x20;     charts/

&#x20;     reports/

&#x20;   tests/

&#x20; requirements.txt

&#x20; .env.example

&#x20; Dockerfile

```



\---



\## 十六、前端目录建议



```text

frontend/

&#x20; src/

&#x20;   api/

&#x20;     client.js

&#x20;     files.js

&#x20;     tasks.js

&#x20;     reports.js

&#x20;   pages/

&#x20;     Dashboard.jsx

&#x20;     Upload.jsx

&#x20;     Workspace.jsx

&#x20;     TaskHistory.jsx

&#x20;     Settings.jsx

&#x20;   components/

&#x20;     FileUploader.jsx

&#x20;     FileList.jsx

&#x20;     TaskInput.jsx

&#x20;     AgentTrace.jsx

&#x20;     ChartViewer.jsx

&#x20;     ReportViewer.jsx

&#x20;   App.jsx

&#x20;   main.jsx

&#x20; package.json

&#x20; vite.config.js

&#x20; Dockerfile

```



\---



\## 十七、每次改完代码后的回复格式



AI 每次改完代码后，必须用中文告诉你：



```text

已完成：



1\. 修改了哪些文件

2\. 实现了什么功能

3\. 如何验证

4\. 已实际运行的验证

5\. 未验证的部分

6\. 需要用户下一步做什么

```



如果没有改文件，要明确说：



```text

未改动文件。

```



不能夸大结果。



没有实际测试过，就不能说“已通过测试”。



\---



\## 十八、最终原则



这个项目要按照“可控、可验证、能写进简历”的标准开发。



优先级是：



1\. 正确；

2\. 安全；

3\. 小改动；

4\. 结构清晰；

5\. 可验证；

6\. 简历价值；

7\. 速度。
