import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button } from "../components/common";
import PasswordField from "../components/common/PasswordField";
import { useAuth } from "../context/AuthContext";
import { AuthPage } from "./Login";

export default function ChangePassword() {
  const { changePassword } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    current_password: "", new_password: "", new_password_confirm: "",
  });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const passwordError = form.new_password && form.new_password.length < 10
    ? "新密码至少需要 10 个字符"
    : "";
  const confirmError = form.new_password_confirm && form.new_password !== form.new_password_confirm
    ? "两次输入的新密码不一致"
    : "";

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await changePassword(form);
      navigate("/workspaces", { replace: true });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPage title="必须先修改密码" description="管理员签发的临时密码只用于本次登录。完成修改后，旧会话会被撤销。">
      <Alert title="为什么需要修改" tone="warning">这是强制安全步骤，完成前无法进入其他页面。</Alert>
      <form className="auth-form" onSubmit={handleSubmit}>
        <PasswordField label="当前密码或临时密码" required autoComplete="current-password"
          value={form.current_password}
          onChange={(event) => setForm({ ...form, current_password: event.target.value })} />
        <PasswordField label="新密码" hint="至少 10 个字符，并避免与当前密码相同。" error={passwordError}
          required autoComplete="new-password" value={form.new_password}
          onChange={(event) => setForm({ ...form, new_password: event.target.value })} />
        <PasswordField label="确认新密码" error={confirmError} required autoComplete="new-password"
          value={form.new_password_confirm}
          onChange={(event) => setForm({ ...form, new_password_confirm: event.target.value })} />
        {error && <Alert title="密码未更新" tone="danger">{error}</Alert>}
        <Button type="submit" size="lg" loading={isSubmitting}
          disabled={Boolean(passwordError || confirmError)}>保存新密码</Button>
      </form>
    </AuthPage>
  );
}
