import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Skeleton } from "./common";

export function RequireSession({ allowPasswordChange = false }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) {
    return <main className="route-loading" aria-label="正在恢复登录状态"><Skeleton lines={5} /></main>;
  }
  if (!user) {
    return <Navigate to="/login" state={{
      from: location,
      message: location.pathname !== "/workspaces" ? "登录状态已失效，请重新登录。" : null,
    }} replace />;
  }
  if (user.must_change_password && !allowPasswordChange) {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}

export function RequireAdmin() {
  const { user } = useAuth();
  if (user?.role !== "admin") {
    return <Navigate to="/forbidden" replace />;
  }
  return <Outlet />;
}
