import { useEffect, useState } from "react";

import { getJson } from "../api/client";
import { useOperationsEvents } from "../events/OperationsEvents";

export interface QueryState<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

const POLL_MS = 10_000;

/** Live query: refetches on websocket events AND on a 10s poll, keeping
 * the previous data during refreshes so pages never flash to skeletons. */
export function useOperations<T>(path: string): QueryState<T> {
  const [state, setState] = useState<QueryState<T>>({ loading: true });
  const [tick, setTick] = useState(0);
  const { revision } = useOperationsEvents();

  useEffect(() => {
    const timer = setInterval(() => setTick((value) => value + 1), POLL_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;
    void getJson<T>(path)
      .then(
        (data) =>
          active && setState({ data, loading: false }),
      )
      .catch((error: unknown) => {
        if (active) {
          setState((previous) => ({
            data: previous.data,
            error: error instanceof Error ? error.message : "Data unavailable",
            loading: false,
          }));
        }
      });
    return () => {
      active = false;
    };
  }, [path, revision, tick]);
  return state;
}
