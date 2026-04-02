/** Run configuration matching the backend WorkflowConfig model. */
export interface WorkflowConfig {
  task: string;
  model: string;
  worker_model?: string;
  api_key?: string;
  max_loops: number;
  max_total_tokens: number;
  max_wall_time: number;
  max_tool_calls: number;
  max_total_workers: number;
  max_depth: number;
  sandbox: 'subprocess' | 'docker' | 'venv' | 'none';
  packages: string[];
  code_mode: boolean;
  tool_creation: boolean;
  tools: string[];
  forbidden_tools: string[];
  verbose: boolean;
  output_dir: string;
  input_files: string[];
  skills_dir: string;
}

/** WebSocket event types pushed from the backend during a run. */
export type RunEventType =
  | 'agent.start'
  | 'agent.complete'
  | 'tool.call'
  | 'tool.result'
  | 'iteration.start'
  | 'iteration.decision'
  | 'budget.update'
  | 'worker.spawn'
  | 'worker.complete'
  | 'delegation.start'
  | 'run.start'
  | 'run.complete'
  | 'error'
  | 'graph.update'
  | 'log';

export interface RunEvent {
  run_id?: string;
  seq?: number;
  type: RunEventType;
  timestamp: string;
  data: Record<string, unknown>;
}

/** Status values for graph nodes. */
export type NodeStatus = 'running' | 'complete' | 'error' | 'pending';

/** Node types rendered in the agent graph. */
export type AgentNodeType =
  | 'task'
  | 'manager'
  | 'iteration'
  | 'worker'
  | 'toolCall'
  | 'completion';

/** Data payload carried by each graph node. */
export interface AgentNodeData {
  label: string;
  status: NodeStatus;
  confidence?: number;
  details: Record<string, unknown>;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  timing?: {
    start: string;
    end?: string;
    duration_ms?: number;
  };
  tools_used?: string[];
  error?: string;
}

/** Agent graph node for React Flow. */
export interface AgentNode {
  id: string;
  type: AgentNodeType;
  data: AgentNodeData;
}

/** Graph edge from the backend. */
export interface AgentEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  animated?: boolean;
}

/** History entry for completed/in-progress runs. */
export interface RunHistoryEntry {
  run_id: string;
  task: string;
  model: string;
  status: string;
  created_at: string;
  completed_at?: string;
  metadata?: Record<string, unknown>;
}

/** Detailed run info returned by GET /api/runs/:id. */
export interface RunDetail {
  id: string;
  task: string;
  model: string;
  status: string;
  config: WorkflowConfig;
  created_at: string;
  completed_at?: string;
  events: RunEvent[];
  result?: Record<string, unknown>;
  error?: string;
}

/** Output content block rendered in the output panel. */
export type OutputBlockType =
  | 'markdown'
  | 'code'
  | 'image'
  | 'chart'
  | 'table'
  | 'json'
  | 'error'
  | 'file';

export interface OutputBlock {
  type: OutputBlockType;
  content: string;
  language?: string;
  title?: string;
  metadata?: Record<string, unknown>;
}

/** A loaded AWP skill. */
export interface Skill {
  name: string;
  description: string;
  path: string;
  loaded: boolean;
}

/** MCP server configuration (for connecting). */
export interface MCPServerConfig {
  name: string;
  command: string;
  args: string[];
  env?: Record<string, string>;
}

/** MCP server state (after connection). */
export interface MCPServer {
  name: string;
  command: string;
  args: string[];
  env?: Record<string, string>;
  connected: boolean;
  tools: string[];
}

/** Budget state tracked during a run. */
export interface BudgetState {
  loops_used: number;
  loops_max: number;
  tokens_used: number;
  tokens_max: number;
  workers_used: number;
  workers_max: number;
  wall_time_ms: number;
  wall_time_max_ms: number;
  tool_calls_used: number;
  tool_calls_max: number;
}

/** Active panel in the main content area. */
export type ActivePanel = 'protocol' | 'output' | 'results' | 'graph' | 'graphvis' | 'memory' | 'history' | 'settings';

/** WebSocket connection handle. */
export interface WebSocketConnection {
  close: () => void;
  send: (data: unknown) => void;
  readyState: () => number;
}

/** Experiment status lifecycle. */
export type ExperimentStatus = 'draft' | 'running' | 'complete' | 'failed' | 'archived';

/** A workflow experiment (formerly session). */
export interface Session {
  id: string;
  title: string;
  description: string;
  hypothesis: string;
  status: ExperimentStatus;
  tags: string[];
  base_dir: string | null;
  created_at: string;
  updated_at: string;
  run_count: number;
  last_run_status: string | null;
}

/** A single experiment memory entry. */
export interface MemoryEntry {
  id: number;
  session_id: string;
  run_id?: string | null;
  type: 'note' | 'observation' | 'finding' | 'decision';
  content: string;
  source: 'user' | 'agent' | 'system';
  created_at: string;
  updated_at: string;
}

/** Detailed session/experiment info including run history, settings, and memory. */
export interface SessionDetail extends Session {
  runs: RunHistoryEntry[];
  settings: Record<string, unknown>;
  memory: MemoryEntry[];
}

/** A single history item within a session (task or result). */
export interface SessionHistoryItem {
  role: 'user' | 'assistant';
  content: string;
  run_id?: string;
  timestamp: string;
  status?: string;
  metadata?: Record<string, unknown>;
}

/** A stored secret key (value is never exposed to the frontend). */
export interface SecretEntry {
  key: string;
  created_at: string;
  updated_at: string;
}
