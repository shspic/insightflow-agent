import { Link, useLocation } from "react-router-dom";

export default function StatusPage({ status = 404, title, description }) {
  const location = useLocation();
  return (
    <main className="standalone-state">
      <p className="eyebrow">错误 {status}</p>
      <h1>{title || (status === 403 ? "没有访问权限" : "页面不存在")}</h1>
      <p>{description || "请检查地址，或返回工作区继续操作。"}</p>
      {location.state?.technicalId && <code>{location.state.technicalId}</code>}
      <Link className="ui-button ui-button--primary" to="/workspaces">返回工作区</Link>
    </main>
  );
}
