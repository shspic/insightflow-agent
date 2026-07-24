import { useEffect, useState } from "react";
import { fetchMyUsage } from "../api/operations";
import {
  Alert,
  Card,
  PageHeader,
  Progress,
  Skeleton,
} from "../components/common";
import { formatBytes, formatDate, quotaState } from "../utils/ui";

const ITEMS = [
  ["daily_tasks", "今日任务", "今天创建的任务数量"],
  ["daily_deepseek_calls", "今日 DeepSeek 调用", "由计划、Agent 和审核产生的模型调用"],
  ["concurrent_tasks", "当前运行任务", "包含排队、执行、审核与重试"],
  ["workspaces", "工作区数量", "未软删除的工作区"],
];

function displayValue(key, value) {
  return key.includes("bytes") ? formatBytes(value) : value ?? 0;
}

export default function Usage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetchMyUsage().then(setData).catch((requestError) => setError(requestError.message));
  }, []);

  return (
    <section className="page-section">
      <PageHeader eyebrow="个人资源边界" title="使用量与配额"
        description="配额由服务端数据库计数。接近上限时先完成或清理现有任务，再等待每日配额重置。" />
      {error && <Alert title="使用量无法加载" tone="danger">{error}</Alert>}
      {!data && !error && <div className="usage-grid"><Skeleton lines={4} /><Skeleton lines={4} /></div>}
      {data && (
        <>
          {Object.entries(data.usage).some(([key, usage]) => quotaState(usage, data.limits[key]).warning) && (
            <Alert title="有配额已达到 80%" tone="warning">
              请查看下方具体项目。达到上限后，服务端会拒绝新操作但不会取消正在安全执行的任务。
            </Alert>
          )}
          <div className="usage-grid">
            {ITEMS.map(([key, label, description]) => {
              const state = quotaState(data.usage[key], data.limits[key]);
              const exempt = data.admin_exemptions.includes(key);
              return (
                <Card className="usage-card" key={key}>
                  <div className="section-heading"><strong>{label}</strong>
                    {exempt && <span className="ui-badge ui-badge--info">管理员豁免</span>}</div>
                  <p className="usage-value">{displayValue(key, data.usage[key])}
                    <small> / {exempt ? "普通配额豁免" : displayValue(key, data.limits[key])}</small></p>
                  <p className="muted">{description}</p>
                  {!exempt && <Progress value={state.percent} tone={state.tone} />}
                </Card>
              );
            })}
            <Card className="usage-card">
              <strong>文件存储</strong>
              <p className="usage-value">{formatBytes(data.usage.file_storage_bytes)}</p>
              <p className="muted">上传文件占用；文件移除后由服务端清理策略释放。</p>
            </Card>
            <Card className="usage-card">
              <strong>报告存储</strong>
              <p className="usage-value">{formatBytes(data.usage.report_storage_bytes)}</p>
              <p className="muted">报告版本与导出资产占用。</p>
            </Card>
            <Card className="usage-card">
              <strong>总存储</strong>
              <p className="usage-value">{formatBytes(data.usage.storage_bytes)}
                <small> / {data.admin_exemptions.includes("storage_bytes")
                  ? "普通配额豁免" : formatBytes(data.limits.storage_bytes)}</small></p>
              {!data.admin_exemptions.includes("storage_bytes") && (
                <Progress value={quotaState(data.usage.storage_bytes, data.limits.storage_bytes).percent} />
              )}
            </Card>
            <Card className="usage-card">
              <strong>单任务安全上限</strong>
              <p>模型调用最多 {data.limits.task_model_calls} 次</p>
              <p>工具调用最多 {data.limits.task_tool_calls} 次</p>
              <p>单工作区文件最多 {data.limits.workspace_files} 个</p>
              <p className="muted">管理员也受这些系统安全上限约束。</p>
            </Card>
          </div>
          <Alert title="每日配额重置" tone="info">
            下一次重置时间：{formatDate(data.reset_at)}。覆盖状态仅由管理员在受控接口中设置。
          </Alert>
        </>
      )}
    </section>
  );
}
