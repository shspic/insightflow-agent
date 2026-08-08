import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Button, Dropdown, IconButton, Select, Tooltip } from "./common";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";

const NAV_ITEMS = [
  { to: "/engineering/projects", short: "E", label: "engineering", end: false },
  { to: "/general/workspaces", short: "G", label: "general", end: false },
  { to: "/usage", short: "量", label: "使用量", end: true },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => {
    if (!mobileOpen) return undefined;
    const handleKey = (event) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [mobileOpen]);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className={`product-shell ${collapsed ? "is-collapsed" : ""}`}>
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside id="app-sidebar" className={`app-sidebar ${mobileOpen ? "is-open" : ""}`} aria-label="主导航">
        <div className="app-brand">
          <span className="app-brand__mark" aria-hidden="true">
            <img src="/favicon.png" alt="" />
          </span>
          {!collapsed && <div><strong>InsightFlow Agent</strong><small>证据化文档审查工作台</small></div>}
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <Tooltip label={collapsed ? item.label : ""} key={item.to}>
              <NavLink to={item.to} end={item.end} aria-label={collapsed ? item.label : undefined}>
                <span aria-hidden="true">{item.short}</span>
                {!collapsed && item.label}
              </NavLink>
            </Tooltip>
          ))}
          {user.role === "admin" && (
            <Tooltip label={collapsed ? "管理后台" : ""}>
              <NavLink to="/admin" aria-label={collapsed ? "管理后台" : undefined}>
                <span aria-hidden="true">管</span>
                {!collapsed && "管理后台"}
              </NavLink>
            </Tooltip>
          )}
        </nav>
        <div className="sidebar-footer">
          <IconButton
            label={collapsed ? "展开侧栏" : "收起侧栏"}
            variant="ghost"
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? "展开" : "收起导航"}
          </IconButton>
          {!collapsed && <small>服务端状态始终是任务真相来源</small>}
        </div>
      </aside>
      {mobileOpen && <button type="button" className="sidebar-scrim" aria-label="关闭导航" onClick={() => setMobileOpen(false)} />}
      <div className="app-workspace">
        <header className="topbar">
          <IconButton label="打开导航" variant="ghost" className="mobile-menu"
            aria-expanded={mobileOpen} aria-controls="app-sidebar" onClick={() => {
              setCollapsed(false);
              setMobileOpen(true);
            }}>
            菜单
          </IconButton>
          <div className="topbar__context">
            <strong>
              {location.pathname.startsWith("/admin") ? "系统管理"
                : location.pathname.startsWith("/engineering") ? "engineering"
                : location.pathname.startsWith("/general") ? "general"
                : location.pathname.startsWith("/usage") ? "使用量"
                : "InsightFlow Agent"}
            </strong>
            <small>
              {location.pathname.startsWith("/engineering") ? "工程检测服务投标资料辅助审查"
                : location.pathname.startsWith("/general") ? "通用文档分析（旧版）"
                : location.pathname.startsWith("/usage") ? "查看配额、模型用量和存储"
                : "多模态资料分析与报告生成"}
            </small>
          </div>
          <Dropdown label={`${user.username} · ${user.role === "admin" ? "管理员" : "用户"}`}>
            <label className="theme-control">
              <span>界面主题</span>
              <Select value={theme} onChange={(event) => setTheme(event.target.value)}>
                <option value="system">跟随系统</option>
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </Select>
            </label>
            <Button variant="danger" onClick={handleLogout}>退出登录</Button>
          </Dropdown>
        </header>
        <main id="main-content" className="app-content" tabIndex="-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
