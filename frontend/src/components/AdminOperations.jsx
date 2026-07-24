import { useEffect, useState } from "react";
import {
  activatePrompt,
  fetchAdminTasks,
  fetchEvaluationRuns,
  fetchFeedback,
  fetchModelUsage,
  fetchPromptVersions,
  fetchUsageSummary,
  fetchWorkers,
  runCleanupDryRun,
  runDeterministicEvaluation,
} from "../api/operations";
import { useFeedback } from "../context/FeedbackContext";
import { TASK_STATUS, formatDate, statusMeta } from "../utils/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Skeleton,
  StatusBadge,
  Tabs,
} from "./common";

const TABS = [
  ["system", "系统状态"],
  ["tasks", "任务"],
  ["workers", "Worker"],
  ["models", "模型"],
  ["feedback", "反馈"],
  ["prompts", "Prompt 版本"],
  ["evaluations", "评估"],
  ["cleanup", "清理"],
];

export default function AdminOperations() {
  const [data, setData] = useState({});
  const [active, setActive] = useState("system");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const { confirm, toast } = useFeedback();

  async function load() {
    try {
      const [summary, tasks, workers, models, feedback, prompts, evaluations] = await Promise.all([
        fetchUsageSummary(), fetchAdminTasks(), fetchWorkers(), fetchModelUsage(), fetchFeedback(),
        fetchPromptVersions(), fetchEvaluationRuns(),
      ]);
      setData({ summary, tasks, workers, models, feedback, prompts, evaluations });
      setMessage("");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function run(name, action, successMessage) {
    setBusy(name);
    try {
      const result = await action();
      if (successMessage) toast(successMessage);
      await load();
      return result;
    } catch (error) {
      setMessage(error.message);
      return null;
    } finally {
      setBusy("");
    }
  }

  async function handleActivate(item) {
    const accepted = await confirm({
      title: `激活 ${item.prompt_name} ${item.version}？`,
      description: "新任务会使用该安全注册表中的版本。此操作不注册工具，也不会修改历史 Agent 运行记录。",
      confirmLabel: "激活版本",
      tone: "warning",
    });
    if (accepted) await run("prompt", () => activatePrompt(item.id), "Prompt 版本已激活");
  }

  if (isLoading) return <section className="panel"><Skeleton lines={7} /></section>;
  const taskDistribution = data.summary?.operational?.tasks?.status_distribution || {};

  return (
    <section className="panel">
      <Tabs items={TABS.map(([value, label]) => ({ value, label }))} value={active} onChange={setActive}
        label="运行治理模块" />
      {message && <Alert title="管理数据未完成" tone="danger">{message}</Alert>}

      {active === "system" && (
        <div className="overview-grid">
          <Card><span className="muted">任务累计</span>
            <p className="usage-value">{data.summary?.usage?.tasks_created || 0}</p>
            <p>成功 {data.summary?.usage?.tasks_succeeded || 0} · 失败 {data.summary?.usage?.tasks_failed || 0}</p></Card>
          <Card><span className="muted">模型调用</span>
            <p className="usage-value">{data.summary?.usage?.deepseek_calls || 0}</p>
            <p>输入 {data.summary?.usage?.input_tokens || 0} · 输出 {data.summary?.usage?.output_tokens || 0} tokens</p></Card>
          <Card><span className="muted">Worker</span>
            <p className="usage-value">{data.workers?.length || 0}</p>
            <p>{data.workers?.filter((item) => item.status === "healthy" || item.status === "idle").length || 0} 个可用记录</p></Card>
          <Card><span className="muted">任务状态分布</span>
            <div>{Object.entries(taskDistribution).map(([status, count]) =>
              <p key={status}><StatusBadge status={status} dictionary={TASK_STATUS} /> {count}</p>)}</div></Card>
        </div>
      )}

      {active === "tasks" && (
        <Table headers={["任务", "用户 / 工作区", "状态", "进度", "Worker", "错误"]}>
          {(data.tasks || []).map((item) => <tr key={item.id}>
            <td>#{item.id}<br /><small>{item.task_type || "未分类"}</small></td>
            <td>用户 #{item.owner_user_id}<br />工作区 #{item.workspace_id}</td>
            <td><StatusBadge status={item.status} dictionary={TASK_STATUS} /></td>
            <td>{item.progress_percent}%</td><td>{item.worker_id || "—"}</td>
            <td>{item.error_code ? `${item.error_code}：${item.error_message || ""}` : "—"}</td>
          </tr>)}
        </Table>
      )}

      {active === "workers" && (
        <>
          {!data.workers?.length && <Alert title="没有 Worker 心跳" tone="danger">
            API 可以运行，但队列任务不会被领取。请检查独立 Worker 进程和数据库 revision。
          </Alert>}
          <Table headers={["Worker", "健康状态", "当前任务", "最后心跳", "租约", "成功 / 失败"]}>
            {(data.workers || []).map((item) => {
              const age = Date.now() - new Date(item.last_heartbeat_at).getTime();
              const health = Number.isFinite(age) && age < 90_000 ? "healthy" : "unready";
              return <tr key={item.worker_id}><td>{item.worker_id}</td>
                <td><Badge tone={health === "healthy" ? "success" : "danger"}>
                  {health === "healthy" ? "healthy" : "unready"}</Badge></td>
                <td>{item.current_task_id || "空闲"}</td><td>{formatDate(item.last_heartbeat_at)}</td>
                <td>{formatDate(item.lease_expires_at)}</td>
                <td>{item.completed_tasks} / {item.failed_tasks}</td></tr>;
            })}
          </Table>
        </>
      )}

      {active === "models" && (
        <Table headers={["时间", "任务", "Provider / 模型", "Prompt", "状态", "Token", "耗时"]}>
          {(data.models || []).map((item) => <tr key={item.id}>
            <td>{formatDate(item.created_at)}</td><td>#{item.task_id}</td>
            <td>{item.provider}<br /><small>{item.model_name}</small></td>
            <td>{item.prompt_name}<br /><small>{item.prompt_version}</small></td>
            <td>{item.status}{item.error_code ? ` · ${item.error_code}` : ""}</td>
            <td>{item.input_tokens || 0} / {item.output_tokens || 0}</td><td>{item.duration_ms || 0} ms</td>
          </tr>)}
        </Table>
      )}

      {active === "feedback" && (
        <Table headers={["时间", "用户", "任务 / 报告", "类型", "问题分类", "状态"]}>
          {(data.feedback || []).map((item) => <tr key={item.id}>
            <td>{formatDate(item.created_at)}</td><td>#{item.user_id}</td>
            <td>任务 #{item.task_id}<br />报告 #{item.report_id || "—"}</td>
            <td>{item.feedback_type}</td><td>{item.issue_category || "—"}</td><td>{item.status}</td>
          </tr>)}
        </Table>
      )}

      {active === "prompts" && (
        <div className="card-grid">
          {(data.prompts || []).map((item) => <Card key={item.id}>
            <div className="section-heading"><strong>{item.prompt_name}</strong>
              <Badge tone={item.status === "active" ? "success" : "neutral"}>{item.status}</Badge></div>
            <p>版本 {item.version}</p><p className="muted">{item.purpose || "未填写用途"}</p>
            <p><small>哈希：{item.content_hash}</small></p>
            {item.status !== "active" && <Button loading={busy === "prompt"} onClick={() => handleActivate(item)}>激活</Button>}
          </Card>)}
        </div>
      )}

      {active === "evaluations" && (
        <>
          <Alert title="deterministic 是规则自检" tone="warning">
            结果用于检查固定路由、Schema 和规则，不代表真实模型准确率或线上质量。
          </Alert>
          <Button loading={busy === "evaluation"}
            onClick={() => run("evaluation", runDeterministicEvaluation, "规则自检已完成")}>
            运行 deterministic 评估
          </Button>
          <Table headers={["运行", "模式", "状态", "开始", "核心指标"]}>
            {(data.evaluations || []).map((item) => <tr key={item.run_id}>
              <td>#{item.run_id}</td><td>{item.mode}</td><td>{item.status}</td>
              <td>{formatDate(item.started_at)}</td>
              <td>{Object.entries(item.metrics || {}).slice(0, 4).map(([key, value]) =>
                <span key={key}>{key}={String(value)} </span>)}</td>
            </tr>)}
          </Table>
        </>
      )}

      {active === "cleanup" && (
        <Card>
          <h3>清理预览</h3>
          <p>管理端仅开放 dry-run。它会列出可清理记录，不删除活跃工作区、当前报告或有效文件。</p>
          <Button variant="warning" loading={busy === "cleanup"}
            onClick={() => run("cleanup", runCleanupDryRun, "清理 dry-run 已完成")}>
            运行清理 dry-run
          </Button>
        </Card>
      )}
    </section>
  );
}

function Table({ headers, children }) {
  const hasRows = Array.isArray(children) ? children.length > 0 : Boolean(children);
  if (!hasRows) return <EmptyState title="暂无记录" description="当前模块还没有可展示的元数据。" />;
  return (
    <div className="table-scroll"><table className="file-table"><thead><tr>
      {headers.map((header) => <th key={header}>{header}</th>)}
    </tr></thead><tbody>{children}</tbody></table></div>
  );
}
