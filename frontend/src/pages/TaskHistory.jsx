import { useCallback, useEffect, useState } from "react";
import { fetchTask, fetchTaskTrace, fetchTasks } from "../api/tasks";
import AgentTrace from "../components/AgentTrace";

function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Date(value).toLocaleString("zh-CN");
}

const STATUS_LABELS = {
  success: "成功",
  failed: "失败",
  running: "执行中",
};

function formatStatus(status) {
  return STATUS_LABELS[status] ?? status ?? "-";
}

function TaskHistory() {
  const [tasks, setTasks] = useState([]);
  const [selectedTask, setSelectedTask] = useState(null);
  const [trace, setTrace] = useState([]);
  const [error, setError] = useState("");

  const loadTasks = useCallback(async () => {
    setError("");

    try {
      const data = await fetchTasks();
      setTasks(data);
    } catch (loadError) {
      setError(loadError.message);
    }
  }, []);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  async function handleSelectTask(taskId) {
    setError("");

    try {
      const [task, taskTrace] = await Promise.all([fetchTask(taskId), fetchTaskTrace(taskId)]);
      setSelectedTask(task);
      setTrace(taskTrace);
    } catch (loadError) {
      setError(loadError.message);
    }
  }

  return (
    <section className="history-section">
      <div className="section-heading">
        <h2>任务历史</h2>
        <button type="button" onClick={loadTasks}>
          刷新历史
        </button>
      </div>

      {error && <p className="form-message form-message--error">{error}</p>}

      <div className="task-history-layout">
        <div className="task-history-list">
          {tasks.length === 0 ? (
            <p className="table-state">暂无历史任务</p>
          ) : (
            tasks.map((task) => (
              <button
                className="task-history-item"
                type="button"
                key={task.id}
                onClick={() => handleSelectTask(task.id)}
              >
                <strong>#{task.id} {task.task_type}</strong>
                <span>{formatStatus(task.status)}</span>
                <span>{task.user_input}</span>
                <span>{formatDate(task.created_at)}</span>
              </button>
            ))
          )}
        </div>

        <div className="task-history-detail">
          {selectedTask ? (
            <>
              <div className="task-result">
                <h3>任务详情</h3>
                <p>状态：{formatStatus(selectedTask.status)}</p>
                <p>类型：{selectedTask.task_type}</p>
                <p>文件 ID：{selectedTask.file_ids.join("，")}</p>
                {selectedTask.status === "failed" && (
                  <p className="form-message form-message--error">任务执行失败，请查看下方失败节点。</p>
                )}
                <pre>{selectedTask.final_answer}</pre>
              </div>
              <AgentTrace trace={trace} />
            </>
          ) : (
            <p className="table-state">请选择一个任务查看详情</p>
          )}
        </div>
      </div>
    </section>
  );
}

export default TaskHistory;
