import type { Status } from "../models/operations";

export function StatusPill({ status }: { status: Status | string }) {
  return (
    <span className={`status status-${status.toLowerCase()}`}>{status}</span>
  );
}
