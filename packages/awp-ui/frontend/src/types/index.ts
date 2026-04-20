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
  trace_enabled: boolean;
  output_dir: string;
  input_files: string[];
  skills_dir: string;
  // Critique
  critique_enabled: boolean;
  critique_max_repair_attempts: number;
  // Manager Intelligence
  planning_enabled: boolean;
  planning_max_subtasks: number;
  diagnosis_enabled: boolean;
  diagnosis_max_hypotheses: number;
  diagnosis_confidence_threshold: number;
  strategy_switching_enabled: boolean;
  budget_reservation_enabled: boolean;
  decision_journal_enabled: boolean;
  decision_journal_max_entries: number;
  // Optimizers — pre-run defaults for the two SGD modes exposed by
  // awp (outer loop over θ, refinement over y). See docs/outer-loop.md
  // and docs/refinement.md. These are NOT invoked inline by
  // `awp run` — they are separate commands/workflows. The config
  // carries the user's preferred defaults so the Optimizer panel
  // and the RefineModal do not need to hard-code them.
  outer_loop_enabled: boolean;
  outer_loop_default_epochs: number;
  outer_loop_default_learning_rate: number;
  outer_loop_with_textgrad: boolean;
  refinement_enabled: boolean;
  refinement_default_iterations: number;
  // Refinement model tiers (low/mid/high). Each tier carries a
  // {manager, worker} pair. Empty strings fall back to the seed run's
  // models at resolve-time (see docs/refinement.md §6.6 and the spec
  // docs/superpowers/specs/2026-04-20-refinement-model-tiers-design.md).
  refinement_tier_low:  { manager: string; worker: string };
  refinement_tier_mid:  { manager: string; worker: string };
  refinement_tier_high: { manager: string; worker: string };
  // Cascade — automatically chain awp refine / awp optimize after seed run
  // completes, scoped to the currently-selected Task in the Experiments sidebar.
  auto_refine_after_seed: boolean;
  auto_refine_iterations: number;
  auto_optimize_after_seed: boolean;
  auto_optimize_epochs: number;
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
  | 'critique.result'
  | 'worker.repair'
  | 'delegation.start'
  | 'run.start'
  | 'run.complete'
  | 'error'
  | 'graph.update'
  | 'llm.call'
  | 'llm.trace_summary'
  | 'log'
  // Metric events — live observability snapshots for the MetricsPanel.
  | 'metric.confidence'
  | 'metric.critique'
  | 'metric.eval'
  | 'metric.budget'
  | 'metric.gate'
  | 'metric.tool_call';

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
  | 'submanager'
  | 'toolCall';

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
  | 'file'
  | 'evaluation';

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
export type ActivePanel = 'protocol' | 'results' | 'workspace' | 'output' | 'graph' | 'graphvis' | 'memory' | 'history' | 'settings' | 'optimizer';

/** WebSocket connection handle. */
export interface WebSocketConnection {
  close: () => void;
  send: (data: unknown) => void;
  readyState: () => number;
}

/** Experiment status lifecycle. */
export type ExperimentStatus = 'draft' | 'running' | 'complete' | 'partial' | 'failed' | 'archived';

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

/** One iteration inside a refinement session — mirrors `RefinementIteration` from awp.refinement.session. */
export interface RefinementIteration {
  k: number;
  run_id: string;
  loss: number;
  status: string;
}

/** Session sidecar (`<seed>/refinement_sessions/<session_id>.json`). */
export interface RefinementSession {
  session_id: string;
  seed_run_id: string;
  started_at: string;
  completed_at: string;
  stop_reason: string;
  best_iter: number;
  iterations: RefinementIteration[];
}

/** BEST pointer manifest (`<seed>/BEST/manifest.json`). */
export interface RefinementBestManifest {
  best_run_id: string;
  best_loss: number;
  seed_loss: number;
  session_id: string;
  winning_run_dir?: string;
}

/** Response payload from `GET /api/experiments/{run_id}/refinement_sessions`. */
export interface RefinementSessionsResponse {
  sessions: RefinementSession[];
  best: RefinementBestManifest | null;
}

/** Response payload from `POST /api/experiments/{run_id}/refine`. */
export interface RefinementStartResponse {
  session_id: string;
  status: string;
}

/** Request body for `POST /api/experiments/{run_id}/refine`.
 *
 * Tier handling (spec 2026-04-20 §10): when any `tier_*` field is set,
 * the backend builds a `TierPlan` and ignores `model`/`worker_model`.
 * Otherwise the legacy single-model path is used.
 */
export interface RefinementStartRequest {
  iterations: number;
  model?: string | null;
  worker_model?: string | null;
  tier_low?: { manager: string; worker: string } | null;
  tier_mid?: { manager: string; worker: string } | null;
  tier_high?: { manager: string; worker: string } | null;
}

/** Snapshot of per-session state for the in-memory session cache. */
export interface CachedSessionState {
  sessionId: string;
  currentRunId: string | null;
  runStatus: 'idle' | 'running' | 'complete' | 'partial' | 'error';
  events: RunEvent[];
  graphNodes: import('reactflow').Node[];
  graphEdges: import('reactflow').Edge[];
  toolRegistry: import('../api/client').ToolRegistryEntry[];
  skillRegistry: import('../api/client').SkillRegistryEntry[];
  outputBlocks: OutputBlock[];
  budget: BudgetState;
  sessionHistory: SessionHistoryItem[];
  experimentMemory: MemoryEntry[];
  config: WorkflowConfig;
  runHistory: RunHistoryEntry[];
  selectedNodeId: string | null;
}
