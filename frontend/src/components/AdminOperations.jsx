import { useEffect, useState } from "react";
import {
  activatePrompt,
  fetchEvaluationRuns,
  fetchFeedback,
  fetchModelUsage,
  fetchPromptVersions,
  fetchUsageSummary,
  fetchWorkers,
  runCleanupDryRun,
  runDeterministicEvaluation,
} from "../api/operations";

export default function AdminOperations() {
  const [data, setData] = useState({});
  const [message, setMessage] = useState("");
  async function load() {
    const [summary, workers, models, feedback, prompts, evaluations] = await Promise.all([
      fetchUsageSummary(), fetchWorkers(), fetchModelUsage(), fetchFeedback(),
      fetchPromptVersions(), fetchEvaluationRuns(),
    ]);
    setData({ summary, workers, models, feedback, prompts, evaluations });
  }
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  async function run(action) {
    try {
      const result = await action();
      setMessage(JSON.stringify(result));
      await load();
    } catch (error) {
      setMessage(error.message);
    }
  }
  return (
    <section className="panel">
      <h3>V2-05 运行治理</h3>
      {message && <p className="form-message">{message}</p>}
      <p>任务状态：{JSON.stringify(data.summary?.operational?.tasks?.status_distribution || {})}</p>
      <p>模型调用：{data.summary?.operational?.models?.calls || 0}；Worker：{data.workers?.length || 0}</p>
      <div className="row-actions">
        <button type="button" onClick={() => run(runDeterministicEvaluation)}>运行 deterministic 评估</button>
        <button type="button" onClick={() => run(runCleanupDryRun)}>清理 dry-run</button>
      </div>
      <details><summary>Worker 状态</summary><pre>{JSON.stringify(data.workers || [], null, 2)}</pre></details>
      <details><summary>模型调用</summary><pre>{JSON.stringify(data.models || [], null, 2)}</pre></details>
      <details><summary>反馈元数据</summary><pre>{JSON.stringify(data.feedback || [], null, 2)}</pre></details>
      <details><summary>评估运行</summary><pre>{JSON.stringify(data.evaluations || [], null, 2)}</pre></details>
      <details>
        <summary>Prompt 版本</summary>
        {(data.prompts || []).map((item) => (
          <div className="task-card" key={item.id}>
            <span>{item.prompt_name} · {item.version} · {item.status}</span>
            {item.status !== "active" && (
              <button type="button" onClick={() => run(() => activatePrompt(item.id))}>激活</button>
            )}
          </div>
        ))}
      </details>
    </section>
  );
}
