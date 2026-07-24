import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { register } from "../api/auth";
import { Alert, Button, FormField, Input } from "../components/common";
import PasswordField from "../components/common/PasswordField";
import { AuthPage } from "./Login";

export default function Register() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    username: "", password: "", password_confirm: "", invite_code: "",
  });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const passwordError = form.password && form.password.length < 10
    ? "密码至少需要 10 个字符"
    : "";
  const confirmError = form.password_confirm && form.password !== form.password_confirm
    ? "两次输入的密码不一致"
    : "";

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await register(form);
      navigate("/login", { replace: true, state: { message: "注册成功，请登录" } });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPage title="创建账号" description="注册需要有效邀请码。邀请码只用于创建账号，系统不会在浏览器中保存。">
      <form className="auth-form" onSubmit={handleSubmit}>
        <FormField label="账号" hint="使用便于识别且不包含敏感信息的账号名。" required>
          <Input required autoFocus autoComplete="username" value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })} />
        </FormField>
        <PasswordField label="密码" hint="使用至少 10 个字符，避免与其他站点重复。" error={passwordError}
          required autoComplete="new-password" value={form.password}
          onChange={(event) => setForm({ ...form, password: event.target.value })} />
        <PasswordField label="确认密码" error={confirmError} required autoComplete="new-password"
          value={form.password_confirm}
          onChange={(event) => setForm({ ...form, password_confirm: event.target.value })} />
        <FormField label="邀请码" required>
          <Input required autoComplete="off" value={form.invite_code}
            onChange={(event) => setForm({ ...form, invite_code: event.target.value })} />
        </FormField>
        {error && <Alert title="注册未成功" tone="danger">{error}</Alert>}
        <Button type="submit" size="lg" loading={isSubmitting}
          disabled={Boolean(passwordError || confirmError)}>注册</Button>
      </form>
      <p className="auth-links"><Link to="/login">已有账号？返回登录</Link></p>
    </AuthPage>
  );
}
