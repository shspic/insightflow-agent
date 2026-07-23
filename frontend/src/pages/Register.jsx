import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { register } from "../api/auth";
import { AuthPage } from "./Login";

export default function Register() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    username: "", password: "", password_confirm: "", invite_code: "",
  });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

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
    <AuthPage title="注册">
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>账号<input required autoComplete="username" value={form.username}
          onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
        <label>密码<input required type="password" autoComplete="new-password" value={form.password}
          onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
        <label>确认密码<input required type="password" autoComplete="new-password"
          value={form.password_confirm}
          onChange={(event) => setForm({ ...form, password_confirm: event.target.value })} /></label>
        <label>邀请码<input required value={form.invite_code}
          onChange={(event) => setForm({ ...form, invite_code: event.target.value })} /></label>
        {error && <p className="form-message form-message--error">{error}</p>}
        <button disabled={isSubmitting}>{isSubmitting ? "提交中…" : "注册"}</button>
      </form>
      <p><Link to="/login">返回登录</Link></p>
    </AuthPage>
  );
}
