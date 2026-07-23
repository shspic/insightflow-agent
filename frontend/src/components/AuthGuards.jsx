import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function RequireSession({ allowPasswordChange = false }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) {
    return <main className="app-shell"><p className="table-state">正在恢复登录状态…</p></main>;
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  if (user.must_change_password && !allowPasswordChange) {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}

export function RequireAdmin() {
  const { user } = useAuth();
  if (user?.role !== "admin") {
    return <Navigate to="/workspaces" replace />;
  }
  return <Outlet />;
}
