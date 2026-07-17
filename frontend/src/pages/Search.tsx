import { FormEvent, useState } from "react";

import { EvidenceTable } from "../components/EvidenceTable";
import { Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";
import type { SearchResult } from "../models/operations";

export function Search() {
  const [input, setInput] = useState("");
  const [term, setTerm] = useState("");
  const state = useOperations<SearchResult>(
    term
      ? `/api/v1/search?q=${encodeURIComponent(term)}`
      : "/api/v1/evaluations?limit=1",
  );
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTerm(input.trim());
  };
  return (
    <Panel title="Global search" meta="Bounded and sanitized">
      <form className="search" onSubmit={submit}>
        <label>
          Evidence identifier or term
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            maxLength={128}
          />
        </label>
        <button type="submit">Search</button>
      </form>
      {state.loading && <div className="state">Searching...</div>}
      {state.error && (
        <div className="state state-error">
          Search unavailable: {state.error}
        </div>
      )}
      <EvidenceTable result={state.data} />
    </Panel>
  );
}
