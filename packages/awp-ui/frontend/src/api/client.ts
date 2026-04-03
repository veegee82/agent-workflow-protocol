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
  MemoryEntry,
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

/** Pre-flight check: verify API key is available for the selected model. */
export async function preflightCheck(
  config: WorkflowConfig,
): Promise<{ ok: boolean; provider: string; required_key?: string; message?: string }> {
  return request('/api/runs/preflight', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

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
  const data = await request<{ runs: RunHistoryEntry[]; total: number }>('/api/runs');
  return data.runs;
}

/** Get full details for a single run. */
export async function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${runId}`);
}

/** Get the event stream for a completed or in-progress run. */
export async function getRunEvents(runId: string): Promise<RunEvent[]> {
  const data = await request<{ events: RunEvent[] }>(`/api/runs/${runId}/events`);
  return data.events;
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

/** Artifact entry from the backend. */
export interface Artifact {
  name: string;
  path: string;
  relative: string;
  kind: 'image' | 'table' | 'html' | 'text' | 'code';
  size: number;
  run_id: string;
}

/** List all output artifacts for a run. */
export async function getRunArtifacts(runId: string): Promise<Artifact[]> {
  const data = await request<{ artifacts: Artifact[] }>(`/api/runs/${runId}/artifacts`);
  return data.artifacts;
}

/** Get the URL to serve a workspace file. */
export function fileServeUrl(filePath: string): string {
  return `${BASE}/api/files/serve?path=${encodeURIComponent(filePath)}`;
}

// ---------------------------------------------------------------------------
// Open directory in system file explorer
// ---------------------------------------------------------------------------

/** Open a directory in the system file explorer. */
export async function openDirectory(path: string): Promise<void> {
  return request<void>('/api/open-directory', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
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

  const res = await fetch(`${BASE}/api/upload`, {
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
  return request<Skill>('/api/skills/load', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

/** Scan a directory for skill files and subdirectories. */
export interface ScannedSkill {
  name: string;
  path: string;
  type: 'file' | 'directory' | 'archive';
  size?: number;
}

export async function scanSkillsDirectory(
  path: string,
): Promise<{ directory: string; skills: ScannedSkill[]; count: number }> {
  return request('/api/skills/scan', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

/** Connect to an MCP server. */
export async function connectMCP(
  config: MCPServerConfig,
): Promise<MCPServer> {
  return request<MCPServer>('/api/tools/mcp', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

/** List all tools available for the current configuration. */
export async function getAvailableTools(): Promise<string[]> {
  const data = await request<{ tools: Array<{ name: string }> }>('/api/tools/available');
  return data.tools.map((t) => t.name);
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

/** Create a new experiment. */
export async function createSession(
  title: string,
  extra?: { description?: string; hypothesis?: string; tags?: string[]; base_dir?: string },
): Promise<Session> {
  return request<Session>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ title, ...extra }),
  });
}

/** List all sessions (most recent first). */
export async function listSessions(): Promise<Session[]> {
  const data = await request<{ sessions: Session[] }>('/api/sessions');
  return data.sessions;
}

/** Get full details for a single session. */
export async function getSession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/sessions/${sessionId}`);
}

/** Update experiment metadata. */
export async function updateSession(
  sessionId: string,
  update: Partial<Pick<Session, 'title' | 'description' | 'hypothesis' | 'status' | 'tags' | 'base_dir'>>,
): Promise<void> {
  return request<void>(`/api/sessions/${sessionId}`, {
    method: 'PUT',
    body: JSON.stringify(update),
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
  const data = await request<{ session_id: string; history: SessionHistoryItem[] }>(
    `/api/sessions/${sessionId}/history`,
  );
  return data.history;
}

/** Full session/experiment data including all runs, events, graphs, and memory. */
export interface SessionFull {
  session: {
    id: string;
    title: string;
    description: string;
    hypothesis: string;
    status: string;
    tags: string[];
    base_dir: string | null;
    created_at: string;
    updated_at: string;
    settings: Record<string, unknown>;
  };
  runs: Array<{
    run_id: string;
    task: string;
    model: string;
    status: string;
    config: Record<string, unknown>;
    result: Record<string, unknown> | null;
    events: Array<{ run_id: string; seq: number; type: string; data: Record<string, unknown>; timestamp: string }>;
    graph: { nodes: Array<Record<string, unknown>>; edges: Array<Record<string, unknown>> } | null;
    created_at: string;
    completed_at: string | null;
  }>;
  memory: MemoryEntry[];
}

/** Load full session data for complete restoration. */
export async function getSessionFull(sessionId: string): Promise<SessionFull> {
  return request<SessionFull>(`/api/sessions/${sessionId}/full`);
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
// Experiment Memory
// ---------------------------------------------------------------------------

/** List all memory entries for an experiment. */
export async function getExperimentMemory(sessionId: string): Promise<MemoryEntry[]> {
  const data = await request<{ memory: MemoryEntry[] }>(`/api/sessions/${sessionId}/memory`);
  return data.memory;
}

/** Add a memory entry to an experiment. */
export async function addMemoryEntry(
  sessionId: string,
  entry: { type: string; content: string; source?: string; run_id?: string },
): Promise<MemoryEntry> {
  return request<MemoryEntry>(`/api/sessions/${sessionId}/memory`, {
    method: 'POST',
    body: JSON.stringify(entry),
  });
}

/** Update a memory entry. */
export async function updateMemoryEntry(
  sessionId: string,
  memoryId: number,
  content: string,
): Promise<void> {
  return request<void>(`/api/sessions/${sessionId}/memory/${memoryId}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

/** Delete a memory entry. */
export async function deleteMemoryEntry(
  sessionId: string,
  memoryId: number,
): Promise<void> {
  return request<void>(`/api/sessions/${sessionId}/memory/${memoryId}`, {
    method: 'DELETE',
  });
}

// ---------------------------------------------------------------------------
// Secrets
// ---------------------------------------------------------------------------

/** List stored secret keys (values are never returned). */
export async function listSecrets(): Promise<SecretEntry[]> {
  const data = await request<{ secrets: SecretEntry[] }>('/api/secrets');
  return data.secrets;
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
  settings: Record<string, unknown>,
): Promise<void> {
  return request<void>('/api/settings', {
    method: 'POST',
    body: JSON.stringify(settings),
  });
}

/** Load persisted settings (returns null if none saved). */
export async function loadSettings(): Promise<Record<string, unknown> | null> {
  try {
    return await request<Record<string, unknown>>('/api/settings');
  } catch {
    return null;
  }
}

/** Get server version from health endpoint. */
export async function getVersion(): Promise<string> {
  try {
    const data = await request<{ version: string }>('/api/health');
    return data.version;
  } catch {
    return '?';
  }
}
