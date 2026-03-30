import type {
  WorkflowConfig,
  RunHistoryEntry,
  RunDetail,
  RunEvent,
  AgentNode,
  AgentEdge,
  Skill,
  MCPServer,
  MCPServerConfig,
  Session,
  SessionDetail,
  SessionHistoryItem,
  SecretEntry,
} from '@/types';

/**
 * Resolve the API base URL.
 * In development Vite proxies /api to localhost:8420.
 * In production the frontend is served from the same origin as the API.
 */
function getBaseUrl(): string {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL as string;
  }
  return window.location.origin;
}

const BASE = getBaseUrl();

/** Typed wrapper around fetch that throws on non-2xx responses. */
async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };

  const res = await fetch(url, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.message ?? JSON.stringify(body);
    } catch {
      // ignore parse errors
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }

  // Handle 204 No Content
  if (res.status === 204) {
    return undefined as unknown as T;
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

/** Start a new workflow run. Returns the assigned run ID. */
export async function startRun(
  config: WorkflowConfig,
): Promise<{ run_id: string }> {
  return request<{ run_id: string }>('/api/runs', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

/** List all runs (most recent first). */
export async function listRuns(): Promise<RunHistoryEntry[]> {
  return request<RunHistoryEntry[]>('/api/runs');
}

/** Get full details for a single run. */
export async function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${runId}`);
}

/** Get the event stream for a completed or in-progress run. */
export async function getRunEvents(runId: string): Promise<RunEvent[]> {
  return request<RunEvent[]>(`/api/runs/${runId}/events`);
}

/** Get the agent graph (nodes + edges) for a run. */
export async function getRunGraph(
  runId: string,
): Promise<{ nodes: AgentNode[]; edges: AgentEdge[] }> {
  return request<{ nodes: AgentNode[]; edges: AgentEdge[] }>(
    `/api/runs/${runId}/graph`,
  );
}

/** Request graceful stop of a running workflow. */
export async function stopRun(runId: string): Promise<void> {
  return request<void>(`/api/runs/${runId}/stop`, { method: 'POST' });
}

/** Delete a run and its artifacts. */
export async function deleteRun(runId: string): Promise<void> {
  return request<void>(`/api/runs/${runId}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------

/** Upload files to be attached to a run. Returns server-side paths. */
export async function uploadFiles(
  files: File[],
): Promise<{ paths: string[] }> {
  const form = new FormData();
  for (const f of files) {
    form.append('files', f);
  }

  const res = await fetch(`${BASE}/api/files`, {
    method: 'POST',
    body: form,
  });

  if (!res.ok) {
    throw new Error(`Upload failed: ${res.statusText}`);
  }

  return res.json() as Promise<{ paths: string[] }>;
}

// ---------------------------------------------------------------------------
// Skills & MCP
// ---------------------------------------------------------------------------

/** Load a skill from a local path. */
export async function loadSkill(path: string): Promise<Skill> {
  return request<Skill>('/api/skills', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

/** Connect to an MCP server. */
export async function connectMCP(
  config: MCPServerConfig,
): Promise<MCPServer> {
  return request<MCPServer>('/api/mcp/connect', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

/** List all tools available for the current configuration. */
export async function getAvailableTools(): Promise<string[]> {
  return request<string[]>('/api/tools');
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

/** Create a new session. */
export async function createSession(title: string): Promise<Session> {
  return request<Session>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

/** List all sessions (most recent first). */
export async function listSessions(): Promise<Session[]> {
  return request<Session[]>('/api/sessions');
}

/** Get full details for a single session. */
export async function getSession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/sessions/${sessionId}`);
}

/** Update a session title. */
export async function updateSession(
  sessionId: string,
  title: string,
): Promise<void> {
  return request<void>(`/api/sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
}

/** Delete a session and its runs. */
export async function deleteSession(sessionId: string): Promise<void> {
  return request<void>(`/api/sessions/${sessionId}`, { method: 'DELETE' });
}

/** Get the conversation history for a session. */
export async function getSessionHistory(
  sessionId: string,
): Promise<SessionHistoryItem[]> {
  return request<SessionHistoryItem[]>(
    `/api/sessions/${sessionId}/history`,
  );
}

/** Start a run within a session context. */
export async function startRunInSession(
  sessionId: string,
  config: WorkflowConfig,
): Promise<{ run_id: string }> {
  return request<{ run_id: string }>(
    `/api/sessions/${sessionId}/runs`,
    {
      method: 'POST',
      body: JSON.stringify(config),
    },
  );
}

// ---------------------------------------------------------------------------
// Secrets
// ---------------------------------------------------------------------------

/** List stored secret keys (values are never returned). */
export async function listSecrets(): Promise<SecretEntry[]> {
  return request<SecretEntry[]>('/api/secrets');
}

/** Store a new secret. */
export async function createSecret(
  key: string,
  value: string,
): Promise<void> {
  return request<void>('/api/secrets', {
    method: 'POST',
    body: JSON.stringify({ key, value }),
  });
}

/** Delete a stored secret. */
export async function deleteSecret(key: string): Promise<void> {
  return request<void>(`/api/secrets/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  });
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

/** Retrieve the current default workflow configuration. */
export async function getSettings(): Promise<WorkflowConfig> {
  return request<WorkflowConfig>('/api/settings');
}

/** Save settings to persistent storage. */
export async function saveSettings(
  settings: Partial<WorkflowConfig>,
): Promise<void> {
  return request<void>('/api/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

/** Load persisted settings (returns null if none saved). */
export async function loadSettings(): Promise<Partial<WorkflowConfig> | null> {
  try {
    return await request<Partial<WorkflowConfig>>('/api/settings/saved');
  } catch {
    return null;
  }
}
