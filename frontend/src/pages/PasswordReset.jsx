import { useState } from "react";
import { Link } from "react-router-dom";
import { submitPasswordReset } from "../api/auth";
import { Alert, Button, FormField, Input, Textarea } from "../components/common";
import { AuthPage } from "./Login";

export default function PasswordReset() {
  const [form, setForm] = useState({ username: "", request_note: "" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const result = await submitPasswordReset(form);
      setMessage(result.message);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPage title="申请重置密码" description="申请会由管理员线下核验。无论账号是否存在，页面都使用相同提示。">
      <form className="auth-form" onSubmit={handleSubmit}>
        <FormField label="账号" required>
          <Input required autoFocus autoComplete="username" value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })} />
        </FormField>
        <FormField label="申请说明（可选）" hint="请勿填写旧密码或其他敏感信息。">
          <Textarea rows="4" maxLength="1000" value={form.request_note}
            onChange={(event) => setForm({ ...form, request_note: event.target.value })} />
        </FormField>
        {message && <Alert title="申请已接收" tone="success">{message}</Alert>}
        {error && <Alert title="申请未提交" tone="danger">{error}</Alert>}
        <Button type="submit" size="lg" loading={isSubmitting}>提交申请</Button>
      </form>
      <p className="auth-links"><Link to="/login">返回登录</Link></p>
    </AuthPage>
  );
}
