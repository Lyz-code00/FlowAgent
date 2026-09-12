import type { ReactNode } from "react";

export function StatusBadge({ status }: { status: string | boolean }) {
  const value = typeof status === "boolean" ? (status ? "已连接" : "未配置") : status;
  const normalized = String(value).toLowerCase();
  const tone = ["ready", "succeeded", "processed", "已连接"].includes(normalized)
    ? "success"
    : ["failed", "error", "未配置"].includes(normalized)
      ? "danger"
      : "neutral";
  return <span className={`status status--${tone}`}>{value}</span>;
}

export function PageHeader({
  title,
  description,
  action
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">FLOWAGENT CONTROL CENTER</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header__action">{action}</div>}
    </header>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="empty-state">
      <div className="empty-state__mark">FA</div>
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

export function LoadingBlock() {
  return <div className="loading-block"><span /><span /><span /></div>;
}

export function ErrorBanner({ message }: { message: string }) {
  return <div className="error-banner" role="alert">{message}</div>;
}
