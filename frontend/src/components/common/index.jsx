import { cloneElement, isValidElement, useEffect, useId, useRef } from "react";
import { statusMeta } from "../../utils/ui";

export function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  loadingLabel = "处理中…",
  className = "",
  disabled,
  ...props
}) {
  return (
    <button
      className={`ui-button ui-button--${variant} ui-button--${size} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      aria-label={loading ? loadingLabel : props["aria-label"]}
      {...props}
    >
      <span className={loading ? "ui-button__label is-loading" : "ui-button__label"}>{children}</span>
      {loading && (
        <span className="ui-button__loading" aria-hidden="true">
          <Spinner size="sm" decorative />
          {loadingLabel}
        </span>
      )}
    </button>
  );
}

export function IconButton({ label, children, ...props }) {
  return <Button className="ui-icon-button" aria-label={label} title={label} {...props}>{children}</Button>;
}

export const Input = (props) => <input className="ui-input" {...props} />;
export const Textarea = (props) => <textarea className="ui-input ui-textarea" {...props} />;
export const Select = (props) => <select className="ui-input ui-select" {...props} />;

export function Checkbox({ label, hint, ...props }) {
  return (
    <label className="ui-choice">
      <input type="checkbox" {...props} />
      <span><strong>{label}</strong>{hint && <small>{hint}</small>}</span>
    </label>
  );
}

export function Switch({ label, ...props }) {
  return (
    <label className="ui-switch">
      <input type="checkbox" role="switch" {...props} />
      <span aria-hidden="true" />
      <strong>{label}</strong>
    </label>
  );
}

export function FormField({ label, hint, error, required, children, className = "" }) {
  const generatedId = useId();
  const controlId = isValidElement(children) && children.props.id ? children.props.id : generatedId;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const child = isValidElement(children)
    ? cloneElement(children, {
        id: controlId,
        "aria-describedby": describedBy,
        "aria-invalid": Boolean(error),
        "aria-required": required || undefined,
      })
    : children;
  return (
    <label className={`ui-field ${className}`} htmlFor={controlId}>
      <span className="ui-field__label">{label}{required && <span aria-hidden="true"> *</span>}</span>
      {hint && <small className="ui-field__hint" id={hintId}>{hint}</small>}
      {child}
      {error && <small className="ui-field__error" id={errorId} role="alert">{error}</small>}
    </label>
  );
}

export function Card({ children, className = "", ...props }) {
  return <article className={`ui-card ${className}`} {...props}>{children}</article>;
}

export function Badge({ children, tone = "neutral", className = "" }) {
  return <span className={`ui-badge ui-badge--${tone} ${className}`}>{children}</span>;
}

export function StatusBadge({ status, dictionary }) {
  const meta = statusMeta(status, dictionary);
  return <Badge tone={meta.tone}><span className="ui-status-dot" aria-hidden="true" />{meta.label}</Badge>;
}

export function Alert({ title, children, tone = "info", action, className = "" }) {
  return (
    <div className={`ui-alert ui-alert--${tone} ${className}`} role={tone === "danger" ? "alert" : "status"}>
      <div><strong>{title}</strong>{children && <div>{children}</div>}</div>
      {action}
    </div>
  );
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  busy = false,
  closeOnBackdrop = true,
}) {
  const ref = useRef(null);
  const titleId = useId();
  const descriptionId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const busyRef = useRef(busy);
  busyRef.current = busy;
  useEffect(() => {
    if (!open) return undefined;
    const prior = document.activeElement;
    // 只有 dialog 内没有已聚焦元素时，才聚焦第一个可聚焦元素；
    // 避免覆盖 React autoFocus 已设置的焦点（如表单输入框）
    if (!ref.current?.contains(document.activeElement)) {
      const focusable = ref.current?.querySelector(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      focusable?.focus();
    }
    const handleKey = (event) => {
      if (event.key === "Escape" && !busyRef.current) onCloseRef.current?.();
      if (event.key === "Tab" && ref.current) {
        const items = [...ref.current.querySelectorAll(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        )];
        if (!items.length) return;
        const first = items[0];
        const last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      prior?.focus?.();
    };
  }, [open]);
  if (!open) return null;
  return (
    <div className="ui-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && closeOnBackdrop && !busy) onClose?.();
    }}>
      <section
        ref={ref}
        className={`ui-dialog ui-dialog--${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        aria-busy={busy || undefined}
      >
        <header className="ui-dialog__header">
          <div><h2 id={titleId}>{title}</h2>{description && <p id={descriptionId}>{description}</p>}</div>
          <IconButton label="关闭对话框" variant="ghost" onClick={onClose} disabled={busy}>关闭</IconButton>
        </header>
        <div className="ui-dialog__body">{children}</div>
        {footer && <footer className="ui-dialog__footer">{footer}</footer>}
      </section>
    </div>
  );
}

export function Drawer({ open, onClose, title, children }) {
  return <Dialog open={open} onClose={onClose} title={title} size="drawer">{children}</Dialog>;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  tone = "danger",
  onConfirm,
  onClose,
  busy,
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title} description={description} busy={busy} footer={(
      <>
        <Button variant="secondary" onClick={onClose} disabled={busy}>{cancelLabel}</Button>
        <Button variant={tone} onClick={onConfirm} loading={busy}>{confirmLabel}</Button>
      </>
    )} />
  );
}

export function Tabs({ items, value, onChange, label = "页面分区" }) {
  return (
    <div className="ui-tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          type="button"
          role="tab"
          aria-selected={value === item.value}
          key={item.value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function Tooltip({ label, children }) {
  return <span className="ui-tooltip" data-tooltip={label}>{children}</span>;
}

export function Dropdown({ label, children }) {
  return <details className="ui-dropdown"><summary>{label}</summary><div>{children}</div></details>;
}

export function Skeleton({ lines = 3, className = "" }) {
  return (
    <div className={`ui-skeleton ${className}`} aria-label="内容加载中" role="status">
      {Array.from({ length: lines }, (_, index) => <span key={index} />)}
    </div>
  );
}

export function Spinner({ size = "md", decorative = false, label = "加载中" }) {
  return (
    <span
      className={`ui-spinner ui-spinner--${size}`}
      role={decorative ? undefined : "status"}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative || undefined}
    />
  );
}

export function EmptyState({ title, description, action }) {
  return (
    <div className="ui-empty" role="status">
      <span className="ui-empty__signal" aria-hidden="true" />
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  return (
    <Alert title={error.title} tone="danger" action={onRetry && <Button variant="secondary" onClick={onRetry}>重试</Button>}>
      <p>{error.message}</p>
      <p>{error.action}</p>
      <details><summary>技术错误标识</summary><code>{error.technicalId}</code></details>
    </Alert>
  );
}

export function Pagination({ page, totalPages, onChange }) {
  return (
    <nav className="ui-pagination" aria-label="分页">
      <Button variant="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</Button>
      <span>第 {page} / {Math.max(1, totalPages)} 页</span>
      <Button variant="secondary" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>下一页</Button>
    </nav>
  );
}

export function Progress({ value = 0, label, tone = "brand" }) {
  const normalized = Math.min(100, Math.max(0, Number(value) || 0));
  return (
    <div className={`ui-progress ui-progress--${tone}`}>
      {label && <div><span>{label}</span><strong>{normalized}%</strong></div>}
      <progress max="100" value={normalized}>{normalized}%</progress>
    </div>
  );
}

export function Stepper({ steps, current }) {
  return (
    <ol className="ui-stepper" aria-label="流程进度">
      {steps.map((step, index) => (
        <li key={step} className={index < current ? "is-done" : index === current ? "is-current" : ""}>
          <span>{index + 1}</span><strong>{step}</strong>
        </li>
      ))}
    </ol>
  );
}

export function PageHeader({ eyebrow, title, description, actions, children }) {
  return (
    <header className="ui-page-header">
      <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <p>{description}</p>}</div>
      {actions && <div className="ui-page-header__actions">{actions}</div>}
      {children}
    </header>
  );
}

export function SectionHeader({ title, description, actions }) {
  return (
    <header className="ui-section-header">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {actions && <div className="row-actions">{actions}</div>}
    </header>
  );
}
