import { useEffect, useState } from "react";

import { getJson } from "../api/client";
import { useOperationsEvents } from "../events/OperationsEvents";

export interface QueryState<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

export function useOperations<T>(path: string): QueryState<T> {
  const [state, setState] = useState<QueryState<T>>({ loading: true });
  const { revision } = useOperationsEvents();

  useEffect(() => {
    let active = true;
    void getJson<T>(path)
      .then((data) => active && setState({ data, loading: false }))
      .catch((error: unknown) => {
        if (active) {
          setState({
            error: error instanceof Error ? error.message : "Data unavailable",
            loading: false,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [path, revision]);
  return state;
}
