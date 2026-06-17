function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Date(value).toLocaleString("zh-CN");
}

const NODE_ORDER = ["classify_task", "plan_task", "route_tools", "execute_tool", "write_result", "save_result"];

const STATUS_LABELS = {
  success: "成功",
  failed: "失败",
  running: "执行中",
};

function formatStatus(status) {
  return STATUS_LABELS[status] ?? status ?? "-";
}

function formatJson(value) {
  if (!value) {
    return "";
  }

  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function summarizeJson(value) {
  const formatted = formatJson(value);
  if (!formatted) {
    return "无";
  }

  const compact = formatted.replace(/\s+/g, " ").trim();
  return compact.length > 90 ? `${compact.slice(0, 90)}...` : compact;
}

function sortTrace(trace) {
  return [...trace].sort((left, right) => {
    const leftOrder = NODE_ORDER.indexOf(left.node_name);
    const rightOrder = NODE_ORDER.indexOf(right.node_name);
    const normalizedLeftOrder = leftOrder === -1 ? NODE_ORDER.length : leftOrder;
    const normalizedRightOrder = rightOrder === -1 ? NODE_ORDER.length : rightOrder;

    if (normalizedLeftOrder !== normalizedRightOrder) {
      return normalizedLeftOrder - normalizedRightOrder;
    }

    return new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
  });
}

function AgentTrace({ trace }) {
  if (!trace || trace.length === 0) {
    return <p className="table-state">暂无执行轨迹</p>;
  }

  const orderedTrace = sortTrace(trace);

  return (
    <div className="trace-list">
      {orderedTrace.map((item) => (
        <div className="trace-item" key={item.id}>
          <div className="trace-heading">
            <strong>{item.node_name}</strong>
            <span className={`trace-status trace-status--${item.status}`}>{formatStatus(item.status)}</span>
          </div>
          <p>工具：{item.tool_name}</p>
          <p>耗时：{item.latency_ms ?? 0} ms</p>
          <p>时间：{formatDate(item.created_at)}</p>
          {item.error_message && <p className="form-message form-message--error">{item.error_message}</p>}
          {item.input_json && (
            <details className="trace-json">
              <summary>输入摘要：{summarizeJson(item.input_json)}</summary>
              <pre>{formatJson(item.input_json)}</pre>
            </details>
          )}
          {item.output_json && (
            <details className="trace-json">
              <summary>输出摘要：{summarizeJson(item.output_json)}</summary>
              <pre>{formatJson(item.output_json)}</pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

export default AgentTrace;
