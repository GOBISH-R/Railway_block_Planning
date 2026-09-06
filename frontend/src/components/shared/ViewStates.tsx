import "./ViewStates.css";

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="view-state" role="status" aria-live="polite">
      <div className="view-state__spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({
  title,
  detail,
  onRetry,
}: {
  title: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="view-state view-state--error" role="alert">
      <p className="view-state__title">{title}</p>
      {detail && <p className="view-state__detail">{detail}</p>}
      {onRetry && (
        <button className="view-state__retry" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="view-state">
      <p className="view-state__title">{title}</p>
      {detail && <p className="view-state__detail">{detail}</p>}
    </div>
  );
}
