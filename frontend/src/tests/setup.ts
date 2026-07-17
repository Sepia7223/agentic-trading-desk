import "@testing-library/jest-dom/vitest";

class WebSocketMock {
  static OPEN = 1;
  readyState = WebSocketMock.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() {
    queueMicrotask(() => this.onopen?.());
  }
  close() {
    this.onclose?.();
  }
}

Object.defineProperty(globalThis, "WebSocket", {
  value: WebSocketMock,
  writable: true,
});
