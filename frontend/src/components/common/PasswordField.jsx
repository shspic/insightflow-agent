import { useState } from "react";
import { Input } from "./index";

export default function PasswordField({ label, hint, error, ...props }) {
  const [visible, setVisible] = useState(false);
  return (
    <label className="ui-field">
      <span className="ui-field__label">{label}</span>
      {hint && <small className="ui-field__hint">{hint}</small>}
      <span className="password-control">
        <Input type={visible ? "text" : "password"} aria-invalid={Boolean(error)} {...props} />
        <button
          type="button"
          aria-label={visible ? `隐藏${label}` : `显示${label}`}
          aria-pressed={visible}
          onClick={() => setVisible((value) => !value)}
        >
          {visible ? "隐藏" : "显示"}
        </button>
      </span>
      {error && <small className="ui-field__error" role="alert">{error}</small>}
    </label>
  );
}
