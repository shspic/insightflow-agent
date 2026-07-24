import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { ConfirmDialog } from "../components/common";

const FeedbackContext = createContext(null);

export function FeedbackProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const [confirmation, setConfirmation] = useState(null);
  const sequence = useRef(0);

  const toast = useCallback((message, tone = "success") => {
    const id = ++sequence.current;
    setToasts((current) => [...current.filter((item) => item.message !== message), { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 5000);
  }, []);

  const confirm = useCallback((options) => new Promise((resolve) => {
    setConfirmation({ ...options, resolve });
  }), []);

  const closeConfirmation = (result) => {
    confirmation?.resolve(result);
    setConfirmation(null);
  };

  const value = useMemo(() => ({ toast, confirm }), [toast, confirm]);
  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div className="ui-toast-region" aria-live="polite" aria-label="操作通知">
        {toasts.map((item) => (
          <div className={`ui-toast ui-toast--${item.tone}`} key={item.id}>
            <span>{item.message}</span>
            <button type="button" aria-label="关闭通知" onClick={() =>
              setToasts((current) => current.filter((toastItem) => toastItem.id !== item.id))}>
              关闭
            </button>
          </div>
        ))}
      </div>
      <ConfirmDialog
        open={Boolean(confirmation)}
        title={confirmation?.title}
        description={confirmation?.description}
        confirmLabel={confirmation?.confirmLabel}
        tone={confirmation?.tone}
        onClose={() => closeConfirmation(false)}
        onConfirm={() => closeConfirmation(true)}
      />
    </FeedbackContext.Provider>
  );
}

export function useFeedback() {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error("useFeedback 必须在 FeedbackProvider 内使用");
  return context;
}
