import { Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";
import type { WhyNoTrade as WhyNoTradeModel } from "../models/operations";

export function WhyNoTrade() {
  const state = useOperations<WhyNoTradeModel[]>("/api/v1/why-no-trade");
  return (
    <Panel
      title="Why Didn't We Trade?"
      meta="Deterministic journal reconstruction"
    >
      {state.loading && (
        <div className="state">Reconstructing evaluations...</div>
      )}
      {state.error && (
        <div className="state state-error">
          Evidence unavailable: {state.error}
        </div>
      )}
      {state.data?.length === 0 && (
        <div className="empty">No non-trade evaluations recorded.</div>
      )}
      <div className="decision-list">
        {state.data?.map((item) => (
          <article
            className="decision"
            key={`${item.evaluation_timestamp}-${item.primary_reason}`}
          >
            <div className="decision-head">
              <time>{new Date(item.evaluation_timestamp).toISOString()}</time>
              <strong>{item.final_action}</strong>
            </div>
            <h3>
              {item.instrument ?? "Unknown instrument"}: {item.primary_reason}
            </h3>
            <p>
              Router {item.router_result} / Strategy {item.strategy_result} /
              Risk {item.risk_result}
            </p>
            <div className="gate-columns">
              <div>
                <b>Passed</b>
                {item.passed_gates.map((gate) => (
                  <span key={gate}>{gate}</span>
                ))}
              </div>
              <div>
                <b>Failed</b>
                {item.failed_gates.map((gate) => (
                  <span key={gate}>{gate}</span>
                ))}
              </div>
            </div>
          </article>
        ))}
      </div>
    </Panel>
  );
}
