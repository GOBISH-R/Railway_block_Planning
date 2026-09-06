import { useEffect, useRef, type ReactNode } from "react";
import "./SlideOver.css";

export function SlideOver({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="slide-over-scrim" onClick={onClose}>
      <aside
        className="slide-over"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="slide-over__header">
          <div>
            <h2 className="slide-over__title">{title}</h2>
            {subtitle && <p className="slide-over__subtitle">{subtitle}</p>}
          </div>
          <button
            ref={closeRef}
            className="slide-over__close"
            onClick={onClose}
            aria-label="Close explanation panel"
          >
            &times;
          </button>
        </header>
        <div className="slide-over__body">{children}</div>
      </aside>
    </div>
  );
}
