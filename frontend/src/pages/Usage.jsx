import { useEffect, useState } from "react";
import { fetchMyUsage } from "../api/operations";

const LABELS = {
  daily_tasks: "今日任务数",
  daily_deepseek_calls: "今日 DeepSeek 调用",
  storage_bytes: "总存储字节",
  workspaces: "工作区数量",
  concurrent_tasks: "当前运行任务",
};

export default function Usage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetchMyUsage().then(setData).catch((requestError) => setError(requestError.message));
  }, []);
  return (
    <section className="page-section">
      <h2>个人使用量</h2>
      {error && <p className="form-message form-message--error">{error}</p>}
      {data && (
        <div className="usage-grid">
          {Object.entries(LABELS).map(([key, label]) => (
            <article className="task-card" key={key}>
              <strong>{label}</strong>
              <p>{data.usage[key] ?? 0} / {data.limits[key] ?? "不限制"}</p>
            </article>
          ))}
          <article className="task-card">
            <strong>每日配额重置</strong>
            <p>{new Date(data.reset_at).toLocaleString("zh-CN")}</p>
          </article>
        </div>
      )}
    </section>
  );
}
