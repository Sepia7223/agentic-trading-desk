import { Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";

export function Configuration() {
  const state = useOperations<Record<string, unknown>>("/api/v1/configuration");
  return (
    <Panel title="Configuration" meta="Sanitized read-only projection">
      <div className="notice">Configuration editing is unavailable.</div>
      {state.loading && (
        <div className="state">Loading safe configuration...</div>
      )}
      {state.error && (
        <div className="state state-error">
          Configuration unavailable: {state.error}
        </div>
      )}
      {state.data && (
        <pre className="json-view">{JSON.stringify(state.data, null, 2)}</pre>
      )}
    </Panel>
  );
}
