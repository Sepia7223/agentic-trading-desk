import type { RecordProjection, SearchResult } from "../models/operations";

function short(value: string) {
  return value.length > 12 ? `${value.slice(0, 8)}...` : value;
}

export function EvidenceTable({ result }: { result?: SearchResult }) {
  if (!result || result.records.length === 0)
    return <div className="empty">No journal evidence available.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>UTC timestamp</th>
            <th>Type</th>
            <th>Instrument</th>
            <th>Source</th>
            <th>State</th>
          </tr>
        </thead>
        <tbody>
          {result.records.map((record: RecordProjection) => (
            <tr key={record.journal_record_id}>
              <td>{new Date(record.effective_at).toISOString()}</td>
              <td>{record.record_type}</td>
              <td>{record.instrument ?? record.epic ?? "Unavailable"}</td>
              <td className="mono">{short(record.source_record_id)}</td>
              <td>
                {String(
                  record.payload.status ?? record.payload.action ?? "RECORDED",
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
