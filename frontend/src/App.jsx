import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import { RequireAdmin, RequireSession } from "./components/AuthGuards";
import { AuthProvider } from "./context/AuthContext";
import Admin from "./pages/Admin";
import ChangePassword from "./pages/ChangePassword";
import Login from "./pages/Login";
import PasswordReset from "./pages/PasswordReset";
import Register from "./pages/Register";
import WorkspaceDetail from "./pages/WorkspaceDetail";
import WorkspaceList from "./pages/WorkspaceList";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
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
              <Route element={<RequireAdmin />}>
                <Route path="/admin" element={<Admin />} />
              </Route>
            </Route>
          </Route>
          <Route path="/" element={<Navigate to="/workspaces" replace />} />
          <Route path="*" element={<Navigate to="/workspaces" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
