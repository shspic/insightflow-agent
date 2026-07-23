import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createWorkspace,
  deleteWorkspace,
  fetchWorkspaces,
  restoreWorkspace,
  updateWorkspace,
} from "../api/workspaces";

export default function WorkspaceList() {
  const [items, setItems] = useState([]);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [error, setError] = useState("");

  async function load() {
    try {
      setItems(await fetchWorkspaces(includeDeleted));
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, [includeDeleted]);

  async function handleCreate(event) {
    event.preventDefault();
    try {
      await createWorkspace(form);
      setForm({ name: "", description: "" });
      await load();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function run(action) {
    try {
      await action();
      await load();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <section className="page-section">
      <div className="section-heading">
        <div><h2>工作区</h2><p>文件、任务和报告均按工作区隔离。</p></div>
        <label><input type="checkbox" checked={includeDeleted}
          onChange={(event) => setIncludeDeleted(event.target.checked)} /> 显示已删除</label>
      </div>
      <form className="inline-form" onSubmit={handleCreate}>
        <input required placeholder="工作区名称" value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })} />
        <input placeholder="描述（可选）" value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })} />
        <button>创建工作区</button>
      </form>
      {error && <p className="form-message form-message--error">{error}</p>}
      <div className="card-grid">
        {items.map((item) => (
          <article className="workspace-card" key={item.id}>
            <div className="section-heading">
              <h3>{item.name}</h3>
              <span>{item.is_deleted ? "deleted" : item.status}</span>
            </div>
            <p>{item.description || "暂无描述"}</p>
            <p>文件 {item.file_count} · 任务 {item.task_count}</p>
            <p>更新：{new Date(item.updated_at).toLocaleString("zh-CN")}</p>
            <div className="row-actions">
              {!item.is_deleted && <Link className="button-link" to={`/workspaces/${item.id}`}>进入</Link>}
              {!item.is_deleted && (
                <button type="button" onClick={() => {
                  const name = window.prompt("新的工作区名称", item.name);
                  if (name?.trim()) run(() => updateWorkspace(item.id, { name: name.trim() }));
                }}>重命名</button>
              )}
              {!item.is_deleted && (
                <button type="button" onClick={() => run(() => updateWorkspace(
                  item.id,
                  { status: item.status === "active" ? "archived" : "active" },
                ))}>{item.status === "active" ? "归档" : "重新启用"}</button>
              )}
              {!item.is_deleted && (
                <button type="button" onClick={() => run(() => deleteWorkspace(item.id))}>软删除</button>
              )}
              {item.is_deleted && (
                <button type="button" onClick={() => run(() => restoreWorkspace(item.id))}>恢复</button>
              )}
            </div>
          </article>
        ))}
      </div>
      {items.length === 0 && <p className="table-state">尚无工作区。</p>}
    </section>
  );
}
