import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { AuthPage } from "./Login";

export default function ChangePassword() {
  const { changePassword } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    current_password: "", new_password: "", new_password_confirm: "",
  });
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    try {
      await changePassword(form);
      navigate("/workspaces", { replace: true });
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <AuthPage title="修改密码">
      <p>当前账号必须先修改密码，完成后原有会话将失效。</p>
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>当前密码或临时密码<input required type="password" value={form.current_password}
          onChange={(event) => setForm({ ...form, current_password: event.target.value })} /></label>
        <label>新密码<input required type="password" value={form.new_password}
          onChange={(event) => setForm({ ...form, new_password: event.target.value })} /></label>
        <label>确认新密码<input required type="password" value={form.new_password_confirm}
          onChange={(event) => setForm({ ...form, new_password_confirm: event.target.value })} /></label>
        {error && <p className="form-message form-message--error">{error}</p>}
        <button>保存新密码</button>
      </form>
    </AuthPage>
  );
}
