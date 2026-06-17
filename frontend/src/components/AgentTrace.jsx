function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Date(value).toLocaleString("zh-CN");
}

function AgentTrace({ trace }) {
  if (!trace || trace.length === 0) {
    return <p className="table-state">暂无执行轨迹</p>;
  }

  return (
    <div className="trace-list">
      {trace.map((item) => (
        <div className="trace-item" key={item.id}>
          <div className="trace-heading">
            <strong>{item.node_name}</strong>
            <span>{item.status}</span>
          </div>
          <p>工具：{item.tool_name}</p>
          <p>耗时：{item.latency_ms ?? 0} ms</p>
          <p>时间：{formatDate(item.created_at)}</p>
          {item.error_message && <p className="form-message form-message--error">{item.error_message}</p>}
          {item.input_json && <pre>{item.input_json}</pre>}
          {item.output_json && <pre>{item.output_json}</pre>}
        </div>
      ))}
    </div>
  );
}

export default AgentTrace;
