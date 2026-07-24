import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import { RequireAdmin, RequireSession } from "./components/AuthGuards";
import ErrorBoundary from "./components/ErrorBoundary";
import { Skeleton } from "./components/common";
import { AuthProvider } from "./context/AuthContext";
import Login from "./pages/Login";
const Admin = lazy(() => import("./pages/Admin"));
const ChangePassword = lazy(() => import("./pages/ChangePassword"));
const PasswordReset = lazy(() => import("./pages/PasswordReset"));
const Register = lazy(() => import("./pages/Register"));
const StatusPage = lazy(() => import("./pages/StatusPage"));
const WorkspaceDetail = lazy(() => import("./pages/WorkspaceDetail"));
const WorkspaceList = lazy(() => import("./pages/WorkspaceList"));
const Usage = lazy(() => import("./pages/Usage"));
import "./styles/tokens.css";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
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
                  <Route path="/workspaces" element={<WorkspaceList />} />
                  <Route path="/workspaces/:workspaceId" element={<WorkspaceDetail />} />
                  <Route path="/workspaces/:workspaceId/:section" element={<WorkspaceDetail />} />
                  <Route path="/workspaces/:workspaceId/tasks/:taskId" element={<WorkspaceDetail />} />
                  <Route path="/workspaces/:workspaceId/reports/:taskId" element={<WorkspaceDetail />} />
                  <Route path="/usage" element={<Usage />} />
                  <Route element={<RequireAdmin />}>
                    <Route path="/admin" element={<Admin />} />
                  </Route>
                  <Route path="/forbidden" element={<StatusPage status={403} />} />
                </Route>
              </Route>
              <Route path="/" element={<Navigate to="/workspaces" replace />} />
              <Route path="*" element={<StatusPage status={404} />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </AuthProvider>
    </BrowserRouter>
  );
}
