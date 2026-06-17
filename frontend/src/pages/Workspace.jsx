import { useCallback, useEffect, useState } from "react";
import { fetchFiles } from "../api/files";
import { createTask, fetchTaskTrace } from "../api/tasks";
import AgentTrace from "../components/AgentTrace";
import TaskInput from "../components/TaskInput";

function Workspace() {
  const [files, setFiles] = useState([]);
  const [filesError, setFilesError] = useState("");
  const [taskError, setTaskError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentTask, setCurrentTask] = useState(null);
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
    setTrace([]);

    try {
      const task = await createTask(payload);
      const taskTrace = await fetchTaskTrace(task.id);
      setCurrentTask(task);
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
          <p>状态：{currentTask.status}</p>
          <p>类型：{currentTask.task_type}</p>
          <pre>{currentTask.final_answer}</pre>
        </div>
      )}

      <AgentTrace trace={trace} />
    </section>
  );
}

export default Workspace;
