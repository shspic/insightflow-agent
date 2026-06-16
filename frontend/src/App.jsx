import { useEffect, useState } from "react";
import Upload from "./pages/Upload";
import "./App.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function App() {
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

        <Upload />
      </section>
    </main>
  );
}

export default App;
