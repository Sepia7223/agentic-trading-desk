import { useState } from "react";

import { EvidenceTable } from "../components/EvidenceTable";
import { Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";
import type { RecordProjection } from "../models/operations";

interface Timeline {
  replay_mode: string;
  cutoff_at: string;
  events: RecordProjection[];
}

export function Replay() {
  const [cutoff, setCutoff] = useState(() =>
    new Date().toISOString().slice(0, 16),
  );
  const iso = new Date(cutoff).toISOString();
  const state = useOperations<Timeline>(
    `/api/v1/replay?cutoff_at=${encodeURIComponent(iso)}`,
  );
  return (
    <Panel title="Replay" meta="Immutable cutoff-safe evidence">
      <div className="replay-banner">
        REPLAY MODE - NO OPERATIONAL AUTHORITY
      </div>
      <label className="field">
        Replay cutoff (UTC)
        <input
          type="datetime-local"
          value={cutoff}
          onChange={(event) => setCutoff(event.target.value)}
        />
      </label>
      {state.loading && <div className="state">Building replay...</div>}
      {state.error && (
        <div className="state state-error">
          Replay unavailable: {state.error}
        </div>
      )}
      {state.data && (
        <EvidenceTable
          result={{
            records: state.data.events,
            total_matches: state.data.events.length,
          }}
        />
      )}
    </Panel>
  );
}
