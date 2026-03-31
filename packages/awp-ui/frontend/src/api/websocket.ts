import type { RunEvent, WebSocketConnection } from '@/types';

/** Options for the WebSocket connection. */
interface ConnectOptions {
  /** Maximum number of reconnection attempts (default 8). */
  maxRetries?: number;
  /** Base delay in ms for exponential backoff (default 500). */
  baseDelay?: number;
  /** Called when the underlying connection state changes. */
  onStateChange?: (state: 'connecting' | 'open' | 'closed' | 'error') => void;
}

/**
 * Build the WebSocket URL for a given run.
 * Respects current protocol (ws / wss) and host.
 */
function buildWsUrl(runId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = import.meta.env.VITE_API_BASE_URL
    ? new URL(import.meta.env.VITE_API_BASE_URL as string).host
    : window.location.host;
  return `${proto}//${host}/ws/${runId}`;
}

/**
 * Open a WebSocket connection to stream events for a workflow run.
 *
 * Returns a `WebSocketConnection` handle with `close()`, `send()`,
 * and `readyState()` helpers. The connection will auto-reconnect on
 * unexpected closure using exponential backoff.
 */
export function connectToRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  options: ConnectOptions = {},
): WebSocketConnection {
  const {
    maxRetries = 8,
    baseDelay = 500,
    onStateChange,
  } = options;

  let ws: WebSocket | null = null;
  let retries = 0;
  let intentionallyClosed = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function connect() {
    const url = buildWsUrl(runId);
    ws = new WebSocket(url);
    onStateChange?.('connecting');

    ws.onopen = () => {
      retries = 0;
      onStateChange?.('open');
    };

    ws.onmessage = (ev: MessageEvent) => {
      try {
        const parsed = JSON.parse(ev.data as string) as RunEvent;
        onEvent(parsed);
      } catch {
        // Non-JSON message -- ignore gracefully.
      }
    };

    ws.onerror = () => {
      onStateChange?.('error');
    };

    ws.onclose = () => {
      onStateChange?.('closed');

      if (intentionallyClosed) {
        return;
      }

      if (retries < maxRetries) {
        const delay = baseDelay * Math.pow(2, retries);
        retries += 1;
        reconnectTimer = setTimeout(connect, delay);
      }
    };
  }

  connect();

  return {
    close() {
      intentionallyClosed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      ws?.close();
    },

    send(data: unknown) {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(typeof data === 'string' ? data : JSON.stringify(data));
      }
    },

    readyState() {
      return ws?.readyState ?? WebSocket.CLOSED;
    },
  };
}
