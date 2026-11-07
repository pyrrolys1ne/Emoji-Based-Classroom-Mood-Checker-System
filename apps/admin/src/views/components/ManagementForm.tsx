import { useEffect, useId, useRef, type FormEvent, type ReactNode } from 'react';

export function ManagementForm({
  title,
  busy,
  error,
  submit,
  close,
  children,
}: {
  title: string;
  busy: boolean;
  error: string;
  submit: () => void;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const heading = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={heading}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
    >
      <div className="dialog-header">
        <h2 id={heading}>{title}</h2>
        <button type="button" className="text-button" disabled={busy} onClick={close}>
          关闭
        </button>
      </div>
      <form
        className="management-form"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (!busy) submit();
        }}
      >
        <fieldset disabled={busy}>{children}</fieldset>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="management-actions">
          <button type="button" className="button secondary" disabled={busy} onClick={close}>
            取消
          </button>
          <button className="button" disabled={busy}>
            {busy ? '提交中…' : '确认提交'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
