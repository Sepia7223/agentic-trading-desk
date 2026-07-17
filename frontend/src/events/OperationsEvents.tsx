import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export interface OperationsEvent {
  event_id: string;
  event_type: string;
  created_at: string;
  source_record_ids: string[];
  payload: Record<string, unknown>;
}

interface EventState {
  connected: boolean;
  revision: number;
  lastEvent?: OperationsEvent;
}

const OperationsEventContext = createContext<EventState>({
  connected: false,
  revision: 0,
});

export function OperationsEventProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<EventState>({
    connected: false,
    revision: 0,
  });

  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/ws/events`);
    socket.onopen = () =>
      setState((current) => ({ ...current, connected: true }));
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(String(message.data)) as OperationsEvent;
        if (event.event_id && event.event_type && event.created_at) {
          setState((current) => ({
            connected: true,
            revision: current.revision + 1,
            lastEvent: event,
          }));
        }
      } catch {
        // Malformed events are ignored; REST remains authoritative.
      }
    };
    socket.onclose = () =>
      setState((current) => ({ ...current, connected: false }));
    return () => socket.close();
  }, []);

  const value = useMemo(() => state, [state]);
  return (
    <OperationsEventContext.Provider value={value}>
      {children}
    </OperationsEventContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useOperationsEvents() {
  return useContext(OperationsEventContext);
}
