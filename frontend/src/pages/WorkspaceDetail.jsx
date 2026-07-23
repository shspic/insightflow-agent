import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AgentTrace from "../components/AgentTrace";
import ReportViewer from "../components/ReportViewer";
import TaskExecutionFlow from "../components/TaskExecutionFlow";
import WorkspaceUnderstanding from "../components/WorkspaceUnderstanding";
import { fetchWorkspace } from "../api/workspaces";
import { fetchWorkspaceFiles } from "../api/workspaceFiles";
import {
  fetchWorkspaceReport,
  fetchWorkspaceTasks,
  fetchWorkspaceTaskTrace,
  generateWorkspaceReport,
} from "../api/workspaceTasks";

export default function WorkspaceDetail() {
  const { workspaceId } = useParams();
  const [workspace, setWorkspace] = useState(null);
  const [files, setFiles] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [trace, setTrace] = useState([]);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  async function loadAll() {
    try {
      const [workspaceData, fileData, taskData] = await Promise.all([
        fetchWorkspace(workspaceId),
        fetchWorkspaceFiles(workspaceId),
        fetchWorkspaceTasks(workspaceId),
      ]);
      setWorkspace(workspaceData);
      setFiles(fileData);
      setTasks(taskData);
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    loadAll();
  }, [workspaceId]);

  async function showTrace(taskId) {
    try {
      setTrace(await fetchWorkspaceTaskTrace(workspaceId, taskId));
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function showReport(task) {
    try {
      const value = task.has_report
        ? await fetchWorkspaceReport(workspaceId, task.id)
        : await generateWorkspaceReport(workspaceId, task.id);
      setReport(value);
      setTasks(await fetchWorkspaceTasks(workspaceId));
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <section className="page-section">
      <p><Link to="/workspaces">← 返回工作区列表</Link></p>
      <div className="section-heading">
        <div><h2>{workspace?.name || "工作区"}</h2><p>{workspace?.description}</p></div>
        <span>{workspace?.status}</span>
      </div>
      {error && <p className="form-message form-message--error">{error}</p>}

      <section className="panel">
        <h3>文件理解与关系确认</h3>
        <WorkspaceUnderstanding
          workspaceId={workspaceId}
          files={files}
          onFilesChanged={loadAll}
        />
      </section>

      <section className="panel">
        <h3>V2 可靠分析任务</h3>
        <TaskExecutionFlow
          workspaceId={workspaceId}
          files={files}
          onTaskChanged={loadAll}
        />
      </section>

      <section className="panel">
        <h3>历史任务</h3>
        {tasks.map((task) => (
          <article className="task-card" key={task.id}>
            <p><strong>#{task.id}</strong> {task.user_input}</p>
            <p>状态：{task.status} · 类型：{task.task_type || "-"}</p>
            <p>{task.final_answer}</p>
            <div className="row-actions">
              <button type="button" onClick={() => showTrace(task.id)}>查看执行轨迹</button>
              {(task.has_report || ["success", "completed", "completed_with_warnings"].includes(task.status)) && (
                <button type="button" onClick={() => showReport(task)}>
                  {task.has_report ? "查看报告" : "生成报告"}
                </button>
              )}
            </div>
          </article>
        ))}
        {tasks.length === 0 && <p className="table-state">暂无历史任务。</p>}
      </section>

      <section className="panel"><h3>Agent 执行轨迹</h3><AgentTrace trace={trace} /></section>
      <ReportViewer report={report} />
    </section>
  );
}
