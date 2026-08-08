import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Navigate, useLocation, useParams } from "react-router-dom";
import { fetchWorkspaceFileRelations } from "../api/fileUnderstanding";
import { fetchMyUsage } from "../api/operations";
import { fetchWorkspace } from "../api/workspaces";
import { fetchWorkspaceFiles } from "../api/workspaceFiles";
import { fetchWorkspaceTasks } from "../api/workspaceTasks";
import ReportCenter from "../components/ReportCenter";
import TaskExecutionFlow from "../components/TaskExecutionFlow";
import WorkspaceUnderstanding from "../components/WorkspaceUnderstanding";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  FormField,
  Input,
  PageHeader,
  Pagination,
  Select,
  Skeleton,
  StatusBadge,
} from "../components/common";
import { FILE_STATUS, TASK_STATUS, formatDate, quotaState } from "../utils/ui";

const TABS = [
  ["overview", "概览", ""],
  ["files", "文件", "files"],
  ["relations", "文件关系", "relations"],
  ["context", "Workspace Context", "context"],
  ["analysis", "新建分析", "new-analysis"],
  ["tasks", "任务", "tasks"],
  ["reports", "报告", "reports"],
  ["settings", "设置", "settings"],
];

function workspaceSection(rawSection, taskId) {
  if (taskId && rawSection === "reports") return "reports";
  if (taskId) return "tasks";
  const matched = TABS.find(([, , path]) => path === (rawSection || ""));
  return matched?.[0] || "overview";
}

function workspaceBasePath(workspaceType) {
  return workspaceType === "engineering" ? "/engineering/projects" : "/general/workspaces";
}

function workspaceListPath(workspaceType) {
  return workspaceType === "engineering" ? "/engineering/projects" : "/general/workspaces";
}

export default function WorkspaceDetail({ type }) {
  const { workspaceId, section: rawSection, taskId } = useParams();
  const location = useLocation();
  const section = workspaceSection(rawSection, taskId);
  const [workspace, setWorkspace] = useState(null);
  const [files, setFiles] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [relations, setRelations] = useState([]);
  const [usage, setUsage] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [taskSearch, setTaskSearch] = useState("");
  const [taskStatus, setTaskStatus] = useState("all");
  const [taskPage, setTaskPage] = useState(1);

  async function loadAll() {
    try {
      const [workspaceData, fileData, taskData, relationData, usageData] = await Promise.all([
        fetchWorkspace(workspaceId),
        fetchWorkspaceFiles(workspaceId),
        fetchWorkspaceTasks(workspaceId),
        fetchWorkspaceFileRelations(workspaceId).catch(() => []),
        fetchMyUsage().catch(() => null),
      ]);
      setWorkspace(workspaceData);
      setFiles(fileData);
      setTasks(taskData);
      setRelations(relationData);
      setUsage(usageData);
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => { loadAll(); }, [workspaceId]);

  const basePath = workspace ? workspaceBasePath(workspace.workspace_type) : (type === "engineering" ? "/engineering/projects" : "/general/workspaces");
  const listPath = workspace ? workspaceListPath(workspace.workspace_type) : (type === "engineering" ? "/engineering/projects" : "/general/workspaces");

  const overview = useMemo(() => ({
    ready: files.filter((file) => file.status === "ready").length,
    unready: files.filter((file) => file.status !== "ready").length,
    confirmedRelations: relations.filter((relation) => relation.status === "confirmed").length,
    pendingRelations: relations.filter((relation) => relation.status === "suggested").length,
    running: tasks.filter((task) => ["queued", "running", "reviewing", "retrying"].includes(task.status)).length,
    reports: tasks.filter((task) => task.has_report).length,
  }), [files, tasks, relations]);

  const filteredTasks = useMemo(() => tasks.filter((task) => {
    const query = taskSearch.trim().toLocaleLowerCase("zh-CN");
    return (taskStatus === "all" || task.status === taskStatus)
      && (!query || task.user_input.toLocaleLowerCase("zh-CN").includes(query));
  }), [tasks, taskSearch, taskStatus]);
  const pageSize = 8;
  const pagedTasks = filteredTasks.slice((taskPage - 1) * pageSize, taskPage * pageSize);
  const reportTasks = tasks.filter((task) => task.has_report);
  const storageQuota = usage && quotaState(usage.usage.storage_bytes, usage.limits.storage_bytes);

  if (isLoading) return <section className="page-section"><Skeleton lines={6} /></section>;
  if (!workspace) {
    return <Alert title="工作区无法加载" tone="danger">{error || "工作区不存在或没有访问权限。"}</Alert>;
  }

  // canonical route：URL 类型与实际 workspace_type 不一致时自动纠正
  const currentTypePrefix = type === "engineering" ? "/engineering/projects" : "/general/workspaces";
  const correctPrefix = workspaceBasePath(workspace.workspace_type);
  if (correctPrefix !== currentTypePrefix) {
    // 从当前 URL 提取 workspaceId 之后的后缀，保留 section/taskId/report
    const pathAfterId = location.pathname.split(workspaceId)[1] || "";
    return <Navigate to={`${correctPrefix}/${workspaceId}${pathAfterId}`} replace />;
  }

  return (
    <section className="page-section">
      <PageHeader
        eyebrow={<Link to={listPath}>{workspace?.workspace_type === "engineering" ? "审查项目 / 返回列表" : "工作区 / 返回列表"}</Link>}
        title={workspace.name}
        description={workspace.description || (workspace?.workspace_type === "engineering" ? "尚未填写项目说明。" : "尚未填写工作区说明。")}
        actions={(
          <>
            <Badge tone={workspace.status === "active" ? "success" : "warning"}>
              {workspace.status === "active" ? "使用中" : "已归档"}
            </Badge>
            <Link className="button-link" to={`${basePath}/${workspaceId}/new-analysis`}>新建分析</Link>
          </>
        )}
      />
      <nav className="workspace-tabs" aria-label="工作区模块">
        {TABS.map(([, label, path]) => (
          <NavLink key={label} end={path === ""}
            to={`${basePath}/${workspaceId}${path ? `/${path}` : ""}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      {error && <Alert title="部分内容未加载" tone="danger">{error}</Alert>}

      {section === "overview" && (
        <>
          {storageQuota?.warning && <Alert title="存储配额接近上限" tone={storageQuota.tone}>
            当前已使用 {storageQuota.percent}%；上传前可在使用量页面查看具体上限。
          </Alert>}
          <div className="overview-grid">
            <Card><span className="muted">文件就绪</span><p className="usage-value">{overview.ready} / {files.length}</p>
              <Link to={`${basePath}/${workspaceId}/files`}>{overview.unready ? `${overview.unready} 个待处理` : "查看文件"}</Link></Card>
            <Card><span className="muted">已确认关系</span><p className="usage-value">{overview.confirmedRelations}</p>
              <Link to={`${basePath}/${workspaceId}/relations`}>{overview.pendingRelations ? `${overview.pendingRelations} 个待确认` : "查看关系"}</Link></Card>
            <Card><span className="muted">运行中任务</span><p className="usage-value">{overview.running}</p>
              <Link to={`${basePath}/${workspaceId}/tasks`}>查看任务</Link></Card>
            <Card><span className="muted">可用报告</span><p className="usage-value">{overview.reports}</p>
              <Link to={`${basePath}/${workspaceId}/reports`}>进入报告中心</Link></Card>
          </div>
          <div className="overview-grid">
            <Card>
              <h2>建议下一步</h2>
              {files.length === 0 && <p>上传资料并完成文件理解。</p>}
              {files.length > 0 && overview.unready > 0 && <p>先理解未就绪文件，再确认角色与质量问题。</p>}
              {overview.unready === 0 && overview.pendingRelations > 0 && <p>确认高匹配关系，避免错误合并影响分析。</p>}
              {files.length > 0 && overview.unready === 0 && <p>资料已具备分析条件，可以创建任务草稿。</p>}
              <div className="row-actions">
                <Link className="button-link" to={`${basePath}/${workspaceId}/files`}>管理资料</Link>
                <Link className="button-link" to={`${basePath}/${workspaceId}/new-analysis`}>开始分析</Link>
              </div>
            </Card>
            <Card>
              <h2>最近任务</h2>
              {tasks.slice(0, 4).map((task) => (
                <Link className="recent-item" key={task.id} to={`${basePath}/${workspaceId}/tasks/${task.id}`}>
                  <span>{task.user_input}</span><StatusBadge status={task.status} dictionary={TASK_STATUS} />
                </Link>
              ))}
              {!tasks.length && <p className="muted">暂无任务。</p>}
            </Card>
            <Card>
              <h2>资料概况</h2>
              {[...new Set(files.map((file) => file.file_type).filter(Boolean))].map((type) => (
                <p key={type}>{type.toUpperCase()}：{files.filter((file) => file.file_type === type).length}</p>
              ))}
              {!files.length && <p className="muted">暂无文件。</p>}
            </Card>
          </div>
        </>
      )}

      {section === "files" && (
        <WorkspaceUnderstanding workspaceId={workspaceId} files={files} onFilesChanged={loadAll} mode="files" />
      )}
      {section === "relations" && (
        <WorkspaceUnderstanding workspaceId={workspaceId} files={files} onFilesChanged={loadAll} mode="relations" />
      )}
      {section === "context" && (
        <WorkspaceUnderstanding workspaceId={workspaceId} files={files} onFilesChanged={loadAll} mode="context" />
      )}
      {section === "analysis" && (
        <section className="panel">
          <div><h2>新建分析</h2><p className="muted">选择文件、说明目标、处理必要追问并确认计划后，任务才会进入队列。</p></div>
          <TaskExecutionFlow workspaceId={workspaceId} files={files} onTaskChanged={loadAll} />
        </section>
      )}
      {section === "tasks" && taskId && (
        <TaskExecutionFlow workspaceId={workspaceId} files={files} onTaskChanged={loadAll}
          initialTaskId={Number(taskId)} />
      )}
      {section === "tasks" && !taskId && (
        <>
          <div className="filter-bar">
            <FormField label="搜索需求"><Input type="search" value={taskSearch}
              onChange={(event) => { setTaskSearch(event.target.value); setTaskPage(1); }} /></FormField>
            <FormField label="任务状态"><Select value={taskStatus}
              onChange={(event) => { setTaskStatus(event.target.value); setTaskPage(1); }}>
              <option value="all">全部状态</option>
              {Object.entries(TASK_STATUS).map(([value, meta]) => <option key={value} value={value}>{meta[0]}</option>)}
            </Select></FormField>
            <Link className="button-link" to={`${basePath}/${workspaceId}/new-analysis`}>新建分析</Link>
          </div>
          <div className="file-table-wrap">
            <table className="file-table"><thead><tr>
              <th>用户需求</th><th>状态</th><th>文件数</th><th>创建时间</th><th>更新时间</th><th>报告</th><th>操作</th>
            </tr></thead><tbody>
              {pagedTasks.map((task) => <tr key={task.id}>
                <td title={task.user_input}>{task.user_input.length > 72 ? `${task.user_input.slice(0, 72)}…` : task.user_input}</td>
                <td><StatusBadge status={task.status} dictionary={TASK_STATUS} /></td>
                <td>{task.file_ids.length}</td><td>{formatDate(task.created_at)}</td><td>{formatDate(task.updated_at)}</td>
                <td>{task.has_report ? "有" : "—"}</td>
                <td><Link to={`${basePath}/${workspaceId}/tasks/${task.id}`}>查看详情</Link></td>
              </tr>)}
            </tbody></table>
          </div>
          {!filteredTasks.length && <EmptyState title="暂无匹配任务" description="创建分析任务后，排队、执行和终态会显示在这里。" />}
          <Pagination page={taskPage} totalPages={Math.ceil(filteredTasks.length / pageSize)}
            onChange={setTaskPage} />
        </>
      )}
      {section === "reports" && taskId && <ReportCenter workspaceId={workspaceId} taskId={Number(taskId)} />}
      {section === "reports" && !taskId && (
        <div className="card-grid">
          {reportTasks.map((task) => (
            <Card key={task.id}>
              <StatusBadge status={task.status} dictionary={TASK_STATUS} />
              <h3>{task.user_input}</h3>
              <p className="muted">任务 #{task.id} · 更新于 {formatDate(task.updated_at)}</p>
              <Link className="button-link" to={`${basePath}/${workspaceId}/reports/${task.id}`}>阅读报告</Link>
            </Card>
          ))}
          {!reportTasks.length && <EmptyState title="暂无报告" description="任务完成并生成报告后，会在这里集中展示。" />}
        </div>
      )}
      {section === "settings" && (
        <Card>
          <h2>工作区设置</h2>
          <p><strong>名称：</strong>{workspace.name}</p>
          <p><strong>说明：</strong>{workspace.description || "未填写"}</p>
          <p><strong>状态：</strong>{workspace.status}</p>
          <p className="muted">重命名、编辑描述、归档与永久删除在工作区列表统一操作，以减少误操作入口。</p>
          <Link to={listPath}>返回{workspace?.workspace_type === "engineering" ? "项目列表" : "工作区列表"}</Link>
        </Card>
      )}
    </section>
  );
}
