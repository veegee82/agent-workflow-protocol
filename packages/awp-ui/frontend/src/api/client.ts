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
} from '@/types';

/**
 * Resolve the API base URL.
 * In development the Vite proxy forwards /api to the backend,
 * so we can use a relative path.  In production the frontend is
 * served by the same FastAPI process, so window.location.origin works.
 */
function baseUrl(): string {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL as string;
  }
  return '';
}

/** Thin wrapper around fetch that throws on non-2xx responses. */
async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${baseUrl()}${path}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };

  // Only set Content-Type for non-FormData bodies
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

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

  // 204 No Content
  if (res.status === 204) {
    return undefined as unknown as T;
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Run lifecycle
// ---------------------------------------------------------------------------

/** Start a new workflow run and return the generated run ID. */
export async function startRun(
  config: WorkflowConfig,
): Promise<{ run_id: string }> {
  return request<{ run_id: string }>('/api/runs', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

/** List all past and current runs. */
export async function listRuns(): Promise<RunHistoryEntry[]> {
  return request<RunHistoryEntry[]>('/api/runs');
}

/** Get detailed information for a single run. */
export async function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${runId}`);
}

/** Get all events emitted during a run. */
export async function getRunEvents(runId: string): Promise<RunEvent[]> {
  return request<RunEvent[]>(`/api/runs/${runId}/events`);
}

/** Get the current agent graph (nodes + edges) for a run. */
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

/** Delete a run and its associated data. */
export async function deleteRun(runId: string): Promise<void> {
  return request<void>(`/api/runs/${runId}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// File uploads
// ---------------------------------------------------------------------------

/** Upload one or more files and return their server-side paths. */
export async function uploadFiles(
  files: File[],
): Promise<{ paths: string[] }> {
  const form = new FormData();
  for (const file of files) {
    form.append('files', file);
  }
  return request<{ paths: string[] }>('/api/files', {
    method: 'POST',
    body: form,
  });
}

// ---------------------------------------------------------------------------
// Skills & MCP
// ---------------------------------------------------------------------------

/** Load an AWP skill from a given path. */
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
  return request<MCPServer>('/api/mcp', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

/** Retrieve the list of tools currently available to the runtime. */
export async function getAvailableTools(): Promise<string[]> {
  return request<string[]>('/api/tools');
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

/** Fetch the current default workflow config from the server. */
export async function getSettings(): Promise<WorkflowConfig> {
  return request<WorkflowConfig>('/api/settings');
}
