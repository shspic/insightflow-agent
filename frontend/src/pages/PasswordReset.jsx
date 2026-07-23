import { useState } from "react";
import { Link } from "react-router-dom";
import { submitPasswordReset } from "../api/auth";
import { AuthPage } from "./Login";

export default function PasswordReset() {
  const [form, setForm] = useState({ username: "", request_note: "" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    try {
      const result = await submitPasswordReset(form);
      setMessage(result.message);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <AuthPage title="申请重置密码">
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>账号<input required value={form.username}
          onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
        <label>申请说明（可选）<textarea rows="4" value={form.request_note}
          onChange={(event) => setForm({ ...form, request_note: event.target.value })} /></label>
        {message && <p className="form-message form-message--success">{message}</p>}
        {error && <p className="form-message form-message--error">{error}</p>}
        <button>提交申请</button>
      </form>
      <p><Link to="/login">返回登录</Link></p>
    </AuthPage>
  );
}
