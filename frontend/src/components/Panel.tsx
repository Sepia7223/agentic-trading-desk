import type { ReactNode } from "react";

export function Panel({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: string;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2>{title}</h2>
        {meta && <span>{meta}</span>}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
