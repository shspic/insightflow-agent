import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <main className="app-shell">
      <section className="dashboard">
        <header className="app-header">
          <div>
            <p className="eyebrow">多模态资料分析与报告生成 Agent</p>
            <h1>InsightFlow Agent</h1>
          </div>
          <div className="user-actions">
            <span>{user.username}（{user.role}）</span>
            <button type="button" onClick={handleLogout}>退出登录</button>
          </div>
        </header>
        <nav className="app-tabs">
          <NavLink to="/workspaces">工作区</NavLink>
          {user.role === "admin" && <NavLink to="/admin">管理员后台</NavLink>}
        </nav>
        <Outlet />
      </section>
    </main>
  );
}
