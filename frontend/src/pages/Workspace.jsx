import { useCallback, useEffect, useState } from "react";
import { fetchFiles } from "../api/files";
import { createTask, fetchTaskReport, fetchTaskTrace } from "../api/tasks";
import AgentTrace from "../components/AgentTrace";
import ReportViewer from "../components/ReportViewer";
import TaskInput from "../components/TaskInput";

const STATUS_LABELS = {
  success: "成功",
  failed: "失败",
  running: "执行中",
};

function formatStatus(status) {
  return STATUS_LABELS[status] ?? status ?? "-";
}

function Workspace() {
  const [files, setFiles] = useState([]);
  const [filesError, setFilesError] = useState("");
  const [taskError, setTaskError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentTask, setCurrentTask] = useState(null);
  const [report, setReport] = useState(null);
  const [trace, setTrace] = useState([]);

  const loadFiles = useCallback(async () => {
    setFilesError("");

    try {
      const data = await fetchFiles();
      setFiles(data);
    } catch (error) {
      setFilesError(error.message);
    }
  }, []);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  async function handleSubmit(payload) {
    setIsSubmitting(true);
    setTaskError("");
    setCurrentTask(null);
    setReport(null);
    setTrace([]);

    try {
      const task = await createTask(payload);
      const taskTrace = await fetchTaskTrace(task.id);
      const taskReport = task.report_path ? await fetchTaskReport(task.id) : null;
      setCurrentTask(task);
      setReport(taskReport);
      setTrace(taskTrace);
    } catch (error) {
      setTaskError(error.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="workspace-section">
      <div className="section-heading">
        <h2>任务工作区</h2>
        <button type="button" onClick={loadFiles}>
          刷新文件
        </button>
      </div>

      {filesError && <p className="form-message form-message--error">{filesError}</p>}
      <TaskInput files={files} isSubmitting={isSubmitting} onSubmit={handleSubmit} />
      {taskError && <p className="form-message form-message--error">{taskError}</p>}

      {currentTask && (
        <div className="task-result">
          <h3>任务结果</h3>
          <p>状态：{formatStatus(currentTask.status)}</p>
          <p>类型：{currentTask.task_type}</p>
          {currentTask.status === "failed" && (
            <p className="form-message form-message--error">任务执行失败，请查看下方失败节点。</p>
          )}
          <pre>{currentTask.final_answer}</pre>
        </div>
      )}

      <ReportViewer report={report} />
      <AgentTrace trace={trace} />
    </section>
  );
}

export default Workspace;
