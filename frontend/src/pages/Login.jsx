import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (user) {
    return <Navigate to={user.must_change_password ? "/change-password" : "/workspaces"} replace />;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const result = await login(form);
      const destination = result.must_change_password
        ? "/change-password"
        : location.state?.from?.pathname || "/workspaces";
      navigate(destination, { replace: true });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPage title="登录">
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>账号<input required autoComplete="username" value={form.username}
          onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
        <label>密码<input required type="password" autoComplete="current-password" value={form.password}
          onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
        {error && <p className="form-message form-message--error">{error}</p>}
        <button disabled={isSubmitting}>{isSubmitting ? "登录中…" : "登录"}</button>
      </form>
      <p><Link to="/register">注册账号</Link> · <Link to="/password-reset">申请重置密码</Link></p>
    </AuthPage>
  );
}

export function AuthPage({ title, children }) {
  return (
    <main className="app-shell auth-shell">
      <section className="dashboard auth-card">
        <p className="eyebrow">InsightFlow Agent</p>
        <h1>{title}</h1>
        {children}
      </section>
    </main>
  );
}
