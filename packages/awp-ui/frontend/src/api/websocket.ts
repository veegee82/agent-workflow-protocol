import type { RunEvent, WebSocketConnection } from '@/types';

/** Maximum number of reconnection attempts before giving up. */
const MAX_RECONNECT_ATTEMPTS = 8;

/** Initial delay in ms between reconnection attempts (doubles each time). */
const INITIAL_RECONNECT_DELAY_MS = 500;

/**
 * Resolve the WebSocket URL for a given run.
 * In dev the Vite proxy handles /ws, in prod we derive from the page origin.
 */
function wsUrl(runId: string): string {
  if (import.meta.env.VITE_WS_BASE_URL) {
    return `${import.meta.env.VITE_WS_BASE_URL}/ws/runs/${runId}`;
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/runs/${runId}`;
}

export type ConnectionState = 'connecting' | 'open' | 'closing' | 'closed';

export interface WebSocketOptions {
  /** Called whenever the connection state changes. */
  onStateChange?: (state: ConnectionState) => void;
  /** Called when the connection is permanently lost after all retries. */
  onFatalError?: (error: Event | CloseEvent) => void;
  /** Whether to automatically reconnect on unexpected closure. */
  autoReconnect?: boolean;
}

/**
 * Open a WebSocket connection that streams {@link RunEvent}s for the
 * specified run.  Returns a handle to close the connection or send messages.
 */
export function connectToRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  options: WebSocketOptions = {},
): WebSocketConnection {
  const {
    onStateChange,
    onFatalError,
    autoReconnect = true,
  } = options;

  let ws: WebSocket | null = null;
  let reconnectAttempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let intentionallyClosed = false;

  function setState(state: ConnectionState) {
    onStateChange?.(state);
  }

  function connect() {
    const url = wsUrl(runId);
    setState('connecting');

    ws = new WebSocket(url);

    ws.onopen = () => {
      reconnectAttempts = 0;
      setState('open');
    };

    ws.onmessage = (messageEvent: MessageEvent) => {
      try {
        const parsed: unknown = JSON.parse(messageEvent.data as string);
        if (
          parsed &&
          typeof parsed === 'object' &&
          'type' in parsed &&
          'timestamp' in parsed
        ) {
          onEvent(parsed as RunEvent);
        }
      } catch {
        // Silently discard malformed messages
      }
    };

    ws.onerror = () => {
      // The browser will follow up with an onclose, so we handle reconnection there.
    };

    ws.onclose = (closeEvent: CloseEvent) => {
      setState('closed');

      if (intentionallyClosed) {
        return;
      }

      // Normal closure (1000) or run-complete closure (4000) -- do not reconnect.
      if (closeEvent.code === 1000 || closeEvent.code === 4000) {
        return;
      }

      if (!autoReconnect) {
        onFatalError?.(closeEvent);
        return;
      }

      if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        onFatalError?.(closeEvent);
        return;
      }

      const delay =
        INITIAL_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttempts);
      reconnectAttempts += 1;

      reconnectTimer = setTimeout(() => {
        connect();
      }, delay);
    };
  }

  // Kick off initial connection.
  connect();

  return {
    close() {
      intentionallyClosed = true;
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (ws) {
        setState('closing');
        ws.close(1000, 'client disconnect');
      }
    },

    send(data: unknown) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(typeof data === 'string' ? data : JSON.stringify(data));
      }
    },

    readyState() {
      return ws?.readyState ?? WebSocket.CLOSED;
    },
  };
}
