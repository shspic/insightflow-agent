import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Alert, Button, FormField, Input } from "../components/common";
import PasswordField from "../components/common/PasswordField";
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
    <AuthPage title="欢迎回来" description="登录后继续处理工作区、任务和报告。">
      <form className="auth-form" onSubmit={handleSubmit}>
        {location.state?.message && <Alert title="需要重新登录" tone="warning">{location.state.message}</Alert>}
        <FormField label="账号" required>
          <Input required autoFocus autoComplete="username" value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })} />
        </FormField>
        <PasswordField label="密码" required autoComplete="current-password" value={form.password}
          onChange={(event) => setForm({ ...form, password: event.target.value })} />
        {error && <Alert title="登录未成功" tone="danger">{error}</Alert>}
        <Button type="submit" size="lg" loading={isSubmitting}>登录</Button>
      </form>
      <p className="auth-links"><Link to="/register">注册账号</Link> · <Link to="/password-reset">申请重置密码</Link></p>
    </AuthPage>
  );
}

export function AuthPage({ title, description, children }) {
  return (
    <main className="auth-shell">
      <section className="auth-intro" aria-label="产品说明">
        <div>
          <p className="eyebrow">InsightFlow Agent</p>
          <h1><span>让资料分析过程</span><span>清楚、可控、可核验</span></h1>
        </div>
        <p>上传表格、文档和图片，确认执行计划，查看 Agent 实时进度，最终获得带引用的版本化报告。</p>
        <ul>
          <li>工作区隔离资料、任务与报告</li>
          <li>计划确认后才进入后台执行</li>
          <li>报告支持 Markdown、DOCX 与 PDF</li>
        </ul>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <p className="eyebrow">安全会话登录</p>
          <h2>{title}</h2>
          {description && <p className="auth-card__subtitle">{description}</p>}
          {children}
        </div>
      </section>
    </main>
  );
}
