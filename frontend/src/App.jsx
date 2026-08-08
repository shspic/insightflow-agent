import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import { RequireAdmin, RequireSession } from "./components/AuthGuards";
import ErrorBoundary from "./components/ErrorBoundary";
import { Skeleton } from "./components/common";
import { AuthProvider } from "./context/AuthContext";
import Login from "./pages/Login";
import { resolvePageTitle } from "./utils/ui";
const Admin = lazy(() => import("./pages/Admin"));
const ChangePassword = lazy(() => import("./pages/ChangePassword"));
const PasswordReset = lazy(() => import("./pages/PasswordReset"));
const Register = lazy(() => import("./pages/Register"));
const StatusPage = lazy(() => import("./pages/StatusPage"));
const WorkspaceDetail = lazy(() => import("./pages/WorkspaceDetail"));
const EngineeringProjectDetail = lazy(() => import("./pages/EngineeringProjectDetail"));
const WorkspaceList = lazy(() => import("./pages/WorkspaceList"));
const Usage = lazy(() => import("./pages/Usage"));
import "./styles/tokens.css";
import "./App.css";

function PageTitle() {
  const location = useLocation();
  useEffect(() => {
    document.title = resolvePageTitle(location.pathname);
  }, [location.pathname]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <PageTitle />
      <AuthProvider>
        <ErrorBoundary>
          <Suspense fallback={<main className="route-loading"><Skeleton lines={5} /></main>}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/password-reset" element={<PasswordReset />} />
              <Route element={<RequireSession allowPasswordChange />}>
                <Route path="/change-password" element={<ChangePassword />} />
              </Route>
              <Route element={<RequireSession />}>
                <Route element={<AppLayout />}>
                  {/* V3 工程审查（默认首页） */}
                  <Route path="/engineering/projects" element={<WorkspaceList type="engineering" />} />
                  <Route path="/engineering/projects/:workspaceId" element={<EngineeringProjectDetail />} />
                  <Route path="/engineering/projects/:workspaceId/:section" element={<EngineeringProjectDetail />} />

                  {/* V3 通用分析（旧版） */}
                  <Route path="/general/workspaces" element={<WorkspaceList type="general" />} />
                  <Route path="/general/workspaces/:workspaceId" element={<WorkspaceDetail type="general" />} />
                  <Route path="/general/workspaces/:workspaceId/:section" element={<WorkspaceDetail type="general" />} />
                  <Route path="/general/workspaces/:workspaceId/tasks/:taskId" element={<WorkspaceDetail type="general" />} />
                  <Route path="/general/workspaces/:workspaceId/reports/:taskId" element={<WorkspaceDetail type="general" />} />

                  {/* 旧地址兼容：跳转到 general */}
                  <Route path="/workspaces" element={<Navigate to="/general/workspaces" replace />} />
                  <Route path="/workspaces/:workspaceId" element={<LegacyWorkspaceRedirect redirectType="detail" />} />
                  <Route path="/workspaces/:workspaceId/:section" element={<LegacyWorkspaceRedirect redirectType="section" />} />
                  <Route path="/workspaces/:workspaceId/tasks/:taskId" element={<LegacyWorkspaceRedirect redirectType="task" />} />
                  <Route path="/workspaces/:workspaceId/reports/:taskId" element={<LegacyWorkspaceRedirect redirectType="report" />} />

                  <Route path="/usage" element={<Usage />} />
                  <Route element={<RequireAdmin />}>
                    <Route path="/admin" element={<Admin />} />
                  </Route>
                  <Route path="/forbidden" element={<StatusPage status={403} />} />
                </Route>
              </Route>
              <Route path="/" element={<Navigate to="/engineering/projects" replace />} />
              <Route path="*" element={<StatusPage status={404} />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </AuthProvider>
    </BrowserRouter>
  );
}

function LegacyWorkspaceRedirect({ redirectType }) {
  const { workspaceId, section, taskId } = useParams();
  if (redirectType === "report") {
    return <Navigate to={`/general/workspaces/${workspaceId}/reports/${taskId}`} replace />;
  }
  if (redirectType === "task") {
    return <Navigate to={`/general/workspaces/${workspaceId}/tasks/${taskId}`} replace />;
  }
  if (redirectType === "section") {
    return <Navigate to={`/general/workspaces/${workspaceId}/${section}`} replace />;
  }
  return <Navigate to={`/general/workspaces/${workspaceId}`} replace />;
}
