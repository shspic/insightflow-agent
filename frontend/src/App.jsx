import { useEffect, useState } from "react";
import TaskHistory from "./pages/TaskHistory";
import Upload from "./pages/Upload";
import Workspace from "./pages/Workspace";
import "./App.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function App() {
  const [activePage, setActivePage] = useState("upload");
  const [health, setHealth] = useState({
    status: "checking",
    message: "正在检查后端连接",
  });

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${API_BASE_URL}/api/health`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        setHealth({
          status: "ok",
          message: `${data.app_name} 后端连接正常`,
        });
      })
      .catch((error) => {
        if (error.name === "AbortError") {
          return;
        }

        setHealth({
          status: "error",
          message: "后端连接失败",
        });
      });

    return () => controller.abort();
  }, []);

  return (
    <main className="app-shell">
      <section className="dashboard">
        <p className="eyebrow">多模态文档与数据分析智能体</p>
        <h1>InsightFlow Agent</h1>
        <div className={`status-panel status-panel--${health.status}`}>
          <span className="status-dot" aria-hidden="true" />
          <div>
            <p className="status-label">后端连接状态</p>
            <p className="status-message">{health.message}</p>
          </div>
        </div>

        <nav className="app-tabs">
          <button type="button" className={activePage === "upload" ? "active" : ""} onClick={() => setActivePage("upload")}>
            文件
          </button>
          <button type="button" className={activePage === "workspace" ? "active" : ""} onClick={() => setActivePage("workspace")}>
            工作区
          </button>
          <button type="button" className={activePage === "history" ? "active" : ""} onClick={() => setActivePage("history")}>
            历史
          </button>
        </nav>

        {activePage === "upload" && <Upload />}
        {activePage === "workspace" && <Workspace />}
        {activePage === "history" && <TaskHistory />}
      </section>
    </main>
  );
}

export default App;
