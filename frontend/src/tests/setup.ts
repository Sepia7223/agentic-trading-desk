import "@testing-library/jest-dom/vitest";

class WebSocketMock {
  static OPEN = 1;
  static instances: WebSocketMock[] = [];
  readyState = WebSocketMock.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  constructor() {
    WebSocketMock.instances.push(this);
    queueMicrotask(() => this.onopen?.());
  }
  close() {
    this.onclose?.();
  }
}

Object.defineProperty(globalThis, "__emitOperationsEvent", {
  value: (event: object) => {
    WebSocketMock.instances
      .at(-1)
      ?.onmessage?.({ data: JSON.stringify(event) });
  },
  writable: true,
});

Object.defineProperty(globalThis, "WebSocket", {
  value: WebSocketMock,
  writable: true,
});
