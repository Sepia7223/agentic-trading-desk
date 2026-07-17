import { EvidenceTable } from "../components/EvidenceTable";
import { Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";
import type { RecordProjection, SearchResult } from "../models/operations";

function isRecord(value: unknown): value is RecordProjection {
  return Boolean(
    value && typeof value === "object" && "journal_record_id" in value,
  );
}

function isSearchResult(value: unknown): value is SearchResult {
  return Boolean(value && typeof value === "object" && "records" in value);
}

export function RecordsPage({
  title,
  endpoint,
  notice,
}: {
  title: string;
  endpoint: string;
  notice?: string;
}) {
  const state = useOperations<unknown>(endpoint);
  if (state.loading)
    return <div className="state">Loading journal evidence...</div>;
  if (state.error)
    return (
      <div className="state state-error">Data unavailable: {state.error}</div>
    );
  const result = isSearchResult(state.data)
    ? state.data
    : isRecord(state.data)
      ? { records: [state.data], total_matches: 1 }
      : undefined;
  return (
    <Panel
      title={title}
      meta={
        result
          ? `${result.total_matches} matched records`
          : "Current safe projection"
      }
    >
      {notice && <div className="notice">{notice}</div>}
      {result ? (
        <EvidenceTable result={result} />
      ) : (
        <pre className="json-view">
          {JSON.stringify(state.data ?? {}, null, 2)}
        </pre>
      )}
    </Panel>
  );
}
