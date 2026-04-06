import { create } from 'zustand';
import type { Node, Edge } from 'reactflow';
import type {
  WorkflowConfig,
  RunEvent,
  OutputBlock,
  BudgetState,
  Skill,
  MCPServer,
  RunHistoryEntry,
  ActivePanel,
  WebSocketConnection,
  Session,
  SessionHistoryItem,
  SecretEntry,
  MemoryEntry,
  CachedSessionState,
} from '@/types';
import * as api from '@/api/client';
import { connectToRun } from '@/api/websocket';

// ---------------------------------------------------------------------------
// Helpers – result formatting
// ---------------------------------------------------------------------------

/** Known keys that typically hold the main markdown/text content in agent results. */
const CONTENT_KEYS = ['report_content', 'report', 'answer', 'your', 'result', 'output', 'response', 'summary', 'analysis'];

/**
 * Convert an agent result dict into OutputBlock(s).
 * Extracts the primary markdown content + confidence instead of dumping raw JSON.
 */
/**
 * Unwrap the nested result structure to find the final_result payload.
 * Common shapes:
 *   { result: { delegation_loop: { final_result: { your: "...", confidence: 0.9 } } } }
 *   { delegation_loop: { final_result: { ... } } }
 *   { final_result: { ... } }
 *   { your: "...", confidence: 0.9 }   ← already unwrapped
 */
function unwrapResult(data: Record<string, unknown>): Record<string, unknown> {
  // Try delegation loop nesting first (deepest common pattern)
  const inner = data.result;
  if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
    const innerDict = inner as Record<string, unknown>;
    const dl = innerDict.delegation_loop;
    if (dl && typeof dl === 'object' && !Array.isArray(dl)) {
      const fr = (dl as Record<string, unknown>).final_result;
      if (fr && typeof fr === 'object' && !Array.isArray(fr)) {
        return fr as Record<string, unknown>;
      }
      // delegation_loop itself may have content keys
      return dl as Record<string, unknown>;
    }
    // result.final_result
    const fr2 = innerDict.final_result;
    if (fr2 && typeof fr2 === 'object' && !Array.isArray(fr2)) {
      return fr2 as Record<string, unknown>;
    }
    // result itself has content keys (e.g. { your: "...", confidence: 0.65 })
    const hasContent = CONTENT_KEYS.some((k) => k in innerDict && typeof innerDict[k] === 'string');
    if (hasContent) {
      return innerDict;
    }
  }
  // Top-level final_result
  const fr3 = data.final_result;
  if (fr3 && typeof fr3 === 'object' && !Array.isArray(fr3)) {
    return fr3 as Record<string, unknown>;
  }
  // Already flat — check if it has content keys
  return data;
}

function resultToOutputBlocks(resultData: unknown, title: string): OutputBlock[] {
  // String result – use as-is (markdown or plain text)
  if (typeof resultData === 'string') {
    return [{ type: 'markdown', content: resultData, title }];
  }

  // Not an object – fall back to JSON tree
  if (resultData == null || typeof resultData !== 'object' || Array.isArray(resultData)) {
    return [{ type: 'json', content: JSON.stringify(resultData, null, 2), title }];
  }

  // Unwrap nested result structures to find the actual content
  const dict = unwrapResult(resultData as Record<string, unknown>);
  const confidence = typeof dict.confidence === 'number' ? dict.confidence : undefined;

  // Find the primary content key
  let mainContent: string | undefined;
  let mainKey: string | undefined;
  for (const key of CONTENT_KEYS) {
    if (key in dict && typeof dict[key] === 'string' && (dict[key] as string).length > 0) {
      mainContent = dict[key] as string;
      mainKey = key;
      break;
    }
  }

  // If no known key, try the first string value that's long enough to be content
  if (!mainContent) {
    for (const [k, v] of Object.entries(dict)) {
      if (k === 'confidence') continue;
      if (typeof v === 'string' && v.length > 20) {
        mainContent = v;
        mainKey = k;
        break;
      }
    }
  }

  // No extractable content – show as structured JSON
  if (!mainContent) {
    return [{ type: 'json', content: JSON.stringify(dict, null, 2), title }];
  }

  // Build confidence badge line
  const confLine = confidence !== undefined
    ? `\n\n---\n**Confidence:** ${(confidence * 100).toFixed(0)}%`
    : '';

  // Extract evaluation data (from raw result or unwrapped dict)
  const rawDict = resultData as Record<string, unknown>;
  const evalData = (rawDict._evaluation ?? dict._evaluation) as Record<string, unknown> | undefined;

  // Collect remaining keys (excluding content, confidence, and underscore-prefixed)
  const extraKeys = Object.keys(dict).filter((k) => k !== mainKey && k !== 'confidence' && !k.startsWith('_'));
  const extras: OutputBlock[] = [];
  if (extraKeys.length > 0) {
    const extraDict: Record<string, unknown> = {};
    for (const k of extraKeys) extraDict[k] = dict[k];
    // Only show extras if they contain meaningful data
    const hasContent = extraKeys.some((k) => {
      const v = dict[k];
      if (Array.isArray(v)) return v.length > 0;
      if (typeof v === 'object' && v !== null) return Object.keys(v as Record<string, unknown>).length > 0;
      return v != null && v !== '';
    });
    if (hasContent) {
      extras.push({
        type: 'json',
        content: JSON.stringify(extraDict, null, 2),
        title: 'Additional Data',
      });
    }
  }

  // Add evaluation summary as markdown (robust — always renders)
  if (evalData && typeof evalData === 'object' && 'final_score' in evalData) {
    const ev = evalData as { final_score: number; action?: string; metrics?: Array<{ name: string; score: number; weight: number }>; retries_used?: number };
    const pct = Math.round(ev.final_score * 100);
    const icon = pct >= 75 ? '🟢' : pct >= 50 ? '🟡' : '🔴';
    let md = `## ${icon} Evaluation Score: ${pct}%\n\n`;
    md += `**Action:** ${(ev.action ?? '').replace(/_/g, ' ')}`;
    if (ev.metrics && ev.metrics.length > 0) {
      md += '\n\n| Metric | Score | Weight |\n|--------|------:|-------:|\n';
      for (const m of ev.metrics) {
        const mIcon = m.score >= 0.65 ? '✅' : m.score >= 0.4 ? '⚠️' : '❌';
        md += `| ${mIcon} ${m.name} | ${Math.round(m.score * 100)}% | ${m.weight} |\n`;
      }
    }
    if (ev.retries_used) {
      md += `\n**Retries used:** ${ev.retries_used}`;
    }
    // Eval block goes FIRST so it's always visible at the top
    return [
      { type: 'markdown', content: md, title: 'Evaluation' },
      { type: 'markdown', content: mainContent + confLine, title },
      ...extras,
    ];
  }

  return [
    { type: 'markdown', content: mainContent + confLine, title },
    ...extras,
  ];
}

// ---------------------------------------------------------------------------
// Default values
// ---------------------------------------------------------------------------

const DEFAULT_CONFIG: WorkflowConfig = {
  task: '',
  model: 'openai/gpt-5-nano',
  worker_model: undefined,
  api_key: undefined,
  max_loops: 100,
  max_total_tokens: 10_000_000,
  max_wall_time: 7200,
  max_tool_calls: 250,
  max_total_workers: 1000,
  max_depth: 100,
  sandbox: 'subprocess',
  packages: [],
  code_mode: true,
  tool_creation: true,
  tools: [],
  forbidden_tools: [],
  verbose: true,
  output_dir: '',
  input_files: [],
  skills_dir: '',
  // Critique
  critique_enabled: true,
  critique_max_repair_attempts: 2,
  // Manager Intelligence (all enabled by default)
  planning_enabled: true,
  planning_max_subtasks: 10,
  diagnosis_enabled: true,
  diagnosis_max_hypotheses: 3,
  diagnosis_confidence_threshold: 0.3,
  strategy_switching_enabled: true,
  budget_reservation_enabled: true,
  decision_journal_enabled: true,
  decision_journal_max_entries: 20,
};

const DEFAULT_BUDGET: BudgetState = {
  loops_used: 0,
  loops_max: 100,
  tokens_used: 0,
  tokens_max: 10_000_000,
  workers_used: 0,
  workers_max: 1000,
  wall_time_ms: 0,
  wall_time_max_ms: 7_200_000,
  tool_calls_used: 0,
  tool_calls_max: 250,
};

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

export interface WorkflowStore {
  // Config
  config: WorkflowConfig;
  updateConfig: (partial: Partial<WorkflowConfig>) => void;

  // Run state
  currentRunId: string | null;
  runStatus: 'idle' | 'running' | 'complete' | 'error';
  events: RunEvent[];
  addEvent: (event: RunEvent) => void;

  // Graph
  graphNodes: Node[];
  graphEdges: Edge[];
  addGraphNode: (node: Node) => void;
  addGraphEdge: (edge: Edge) => void;
  updateGraphNode: (id: string, data: Partial<Node['data']>) => void;
  selectedNodeId: string | null;
  selectNode: (id: string | null) => void;
  loadRunGraph: (runId?: string) => Promise<void>;

  // Output
  outputBlocks: OutputBlock[];
  addOutputBlock: (block: OutputBlock) => void;

  // Run selection (for viewing past runs in Output/Results panels)
  selectedRunId: string | null;
  selectRun: (runId: string | null) => void;
  selectedRunBlocks: OutputBlock[];
  loadRunBlocks: (runId: string) => Promise<void>;

  // Budget
  budget: BudgetState;
  updateBudget: (budget: Partial<BudgetState>) => void;

  // UI state
  activePanel: ActivePanel;
  setActivePanel: (panel: ActivePanel) => void;
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  inspectorOpen: boolean;
  toggleInspector: () => void;

  // Skills & Tools
  skills: Skill[];
  mcpServers: MCPServer[];

  // History
  runHistory: RunHistoryEntry[];
  loadHistory: () => Promise<void>;

  // Actions
  startRun: () => Promise<void>;
  stopRun: () => Promise<void>;
  reset: () => void;

  // Files
  attachedFiles: File[];
  addFiles: (files: File[]) => void;
  removeFile: (index: number) => void;

  // Sessions / Experiments
  currentSessionId: string | null;
  sessions: Session[];
  sessionHistory: SessionHistoryItem[];
  createSession: (title?: string) => Promise<void>;
  loadSessions: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  renameSession: (sessionId: string, title: string) => Promise<void>;
  updateSessionMetadata: (sessionId: string, update: Partial<Session>) => Promise<void>;

  // Experiment Memory
  experimentMemory: MemoryEntry[];
  loadExperimentMemory: () => Promise<void>;
  addMemoryEntry: (type: string, content: string, source?: string) => Promise<void>;
  updateMemoryEntry: (memoryId: number, content: string) => Promise<void>;
  deleteMemoryEntry: (memoryId: number) => Promise<void>;

  // Secrets
  secrets: SecretEntry[];
  loadSecrets: () => Promise<void>;
  addSecret: (key: string, value: string) => Promise<void>;
  removeSecret: (key: string) => Promise<void>;

  // Task refactoring
  isRefactoring: boolean;
  refactorTask: () => Promise<void>;

  // Persistent settings
  settingsLoaded: boolean;
  loadPersistedSettings: () => Promise<void>;
  saveCurrentSettings: () => Promise<void>;

  // WebSocket handle (internal)
  _wsConnection: WebSocketConnection | null;
  _wsStatus: 'connecting' | 'open' | 'closed' | 'error';

  // Session cache (internal)
  _sessionCache: Map<string, CachedSessionState>;
  _wsPool: Map<string, WebSocketConnection>;
  _runToSession: Map<string, string>;
}

// ---------------------------------------------------------------------------
// Event processing helpers
// ---------------------------------------------------------------------------

function nodeIdFromEvent(evt: RunEvent): string {
  const d = evt.data;
  return (
    (d.node_id as string | undefined) ??
    (d.agent_id as string | undefined) ??
    (d.worker_id as string | undefined) ??
    evt.type + '-' + evt.timestamp
  );
}

function processEvent(
  evt: RunEvent,
  get: () => WorkflowStore,
  set: (
    partial:
      | Partial<WorkflowStore>
      | ((s: WorkflowStore) => Partial<WorkflowStore>),
  ) => void,
) {
  const isVerbose = get().config.verbose;
  const store = get();

  // Track the last iteration/manager node for linking workers
  const lastManagerId = () => {
    const nodes = store.graphNodes;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const nt = (nodes[i].data as Record<string, unknown>).nodeType ?? nodes[i].type;
      if (nt === 'manager' || nt === 'iteration') return nodes[i].id;
    }
    return null;
  };

  switch (evt.type) {
    // ----- Run lifecycle -----
    case 'run.start': {
      const model =
        (evt.data.model as string) ??
        ((evt.data.models as Record<string, string>)?.manager) ??
        get().config.model;
      // Create root task node
      store.addGraphNode({
        id: 'task_root',
        type: 'default',
        position: { x: 0, y: 0 },
        data: {
          label: get().config.task.slice(0, 60) || 'Task',
          status: 'running',
          nodeType: 'task',
          details: { model },
        },
      });
      // Create manager node
      store.addGraphNode({
        id: 'manager',
        type: 'default',
        position: { x: 0, y: 120 },
        data: {
          label: `Manager (${model.split('/').pop()})`,
          status: 'running',
          nodeType: 'manager',
          details: evt.data,
        },
      });
      store.addGraphEdge({
        id: 'e-task-manager',
        source: 'task_root',
        target: 'manager',
        animated: true,
      });
      store.addOutputBlock({
        type: 'markdown',
        content: `**Run started** — ${model}`,
        title: 'Run',
      });
      break;
    }

    // ----- Agent start -----
    case 'agent.start': {
      const id = nodeIdFromEvent(evt);
      store.addGraphNode({
        id,
        type: 'default',
        position: { x: 0, y: store.graphNodes.length * 120 },
        data: {
          label: (evt.data.agent_name as string) ?? evt.type,
          status: 'running',
          details: evt.data,
          nodeType: 'task',
        },
      });
      break;
    }

    // ----- Sub-manager (recursive delegation) -----
    case 'delegation.start': {
      const parentId = (evt.data.parent_id as string) ?? lastManagerId() ?? 'manager';
      const depth = (evt.data.depth as number) ?? 1;
      const model = (evt.data.model as string) ?? '?';
      const subMgrId = `sub_mgr_${parentId}_d${depth}`;
      store.addGraphNode({
        id: subMgrId,
        type: 'default',
        position: { x: 0, y: store.graphNodes.length * 120 },
        data: {
          label: `Sub-Manager d${depth} (${model.split('/').pop()})`,
          status: 'running',
          nodeType: 'manager',
          depth,
          details: evt.data,
        },
      });
      store.addGraphEdge({
        id: `e-${parentId}-${subMgrId}`,
        source: parentId,
        target: subMgrId,
        animated: true,
      });
      store.addOutputBlock({
        type: 'markdown',
        content: `**Sub-delegation** (depth ${depth}) — ${model}`,
        title: 'Delegation',
      });
      break;
    }

    // ----- Iteration -----
    case 'iteration.start': {
      const iterNum = evt.data.iteration ?? '?';
      const iterId = `iter_${iterNum}`;
      const depth = (evt.data.depth as number) ?? 0;
      // For sub-run iterations, link to the sub-manager; for root, link to 'manager'
      const parentWorkerId = evt.data.parent_id as string | undefined;
      let iterParent = 'manager';
      if (parentWorkerId && depth > 0) {
        // Find the sub-manager node for this parent worker
        const subMgrId = `sub_mgr_${parentWorkerId}_d${depth}`;
        if (store.graphNodes.some((n) => n.id === subMgrId)) {
          iterParent = subMgrId;
        } else {
          iterParent = parentWorkerId;
        }
      }
      store.addGraphNode({
        id: iterId,
        type: 'default',
        position: { x: 0, y: store.graphNodes.length * 120 },
        data: {
          label: `Iteration ${iterNum}`,
          status: 'running',
          nodeType: 'iteration',
          depth,
          details: evt.data,
        },
      });
      // Link to parent manager
      store.addGraphEdge({
        id: `e-${iterParent}-${iterId}`,
        source: iterParent,
        target: iterId,
        animated: true,
      });
      store.addOutputBlock({
        type: 'markdown',
        content: `**Iteration ${iterNum}**${depth > 0 ? ` (depth ${depth})` : ''}`,
        title: 'Iteration',
      });
      break;
    }

    case 'iteration.decision': {
      const iterNum = evt.data.iteration ?? '?';
      const iterId = `iter_${iterNum}`;
      const decision = (evt.data.decision as string) ?? 'unknown';
      const confidence = evt.data.confidence as number | undefined;
      const reasoning = (evt.data.reasoning as string) ?? '';
      const delegations = evt.data.delegations as Array<Record<string, unknown>> | undefined;

      // Update iteration node with decision
      store.updateGraphNode(iterId, {
        status: decision === 'complete' ? 'complete' : 'running',
        label: `Iter ${iterNum}: ${decision.toUpperCase()}`,
        confidence,
        decision,
        reasoning,
        delegations,
        details: evt.data,
      });

      // Build rich output
      let content = `**Decision: ${decision}** (confidence: ${confidence ?? '?'})\n\n`;
      if (reasoning) content += `${reasoning}\n\n`;
      if (delegations && delegations.length > 0) {
        content += `**Delegations (${delegations.length}):**\n`;
        for (const d of delegations) {
          const tools = (d.tools as string[]) ?? [];
          content += `- \`${d.worker}\`: ${d.task}`;
          if (tools.length > 0) content += ` [${tools.join(', ')}]`;
          content += '\n';
        }
      }

      store.addOutputBlock({
        type: 'markdown',
        content,
        title: `Iteration ${iterNum}`,
      });
      break;
    }

    // ----- Workers -----
    case 'worker.spawn': {
      const workerId = (evt.data.worker_id as string) ?? nodeIdFromEvent(evt);
      const instructions = (evt.data.instructions as string) ?? (evt.data.task as string) ?? '';
      const tools = (evt.data.tools_allowed as string[]) ?? [];
      const iteration = (evt.data.iteration as string) ?? '';
      const skills = (evt.data.skills as string[]) ?? [];
      const codeMode = evt.data.code_mode;
      // Link to the iteration node if available, otherwise fall back to manager
      const iterNodeId = iteration ? `iter_${iteration}` : null;
      const iterNodeExists = iterNodeId && store.graphNodes.some((n) => n.id === iterNodeId);
      const parentId = (evt.data.parent_id as string) ?? (iterNodeExists ? iterNodeId! : lastManagerId() ?? 'manager');
      // Include iteration in node ID to avoid collision when same worker name repeats across iterations
      const workerNodeId = iteration ? `${workerId}_${iteration}` : workerId;

      store.addGraphNode({
        id: workerNodeId,
        type: 'default',
        position: { x: 250, y: store.graphNodes.length * 120 },
        data: {
          label: instructions.slice(0, 60) || `Worker ${workerId.slice(0, 8)}`,
          status: 'running',
          nodeType: 'worker',
          tools_used: tools,
          instructions,
          iteration,
          skills,
          code_mode: codeMode,
          details: evt.data,
        },
      });
      store.addGraphEdge({
        id: `e-${parentId}-${workerNodeId}`,
        source: parentId,
        target: workerNodeId,
        animated: true,
      });
      if (isVerbose) {
        store.addOutputBlock({
          type: 'markdown',
          content: `**Worker spawned:** \`${workerId.slice(0, 8)}\`\n\n${instructions.slice(0, 500)}${tools.length ? `\n\nTools: ${tools.join(', ')}` : ''}`,
          title: 'Worker',
        });
      }
      break;
    }

    case 'worker.complete': {
      const workerId = (evt.data.worker_id as string) ?? nodeIdFromEvent(evt);
      const iteration = (evt.data.iteration as string) ?? '';
      const workerNodeId = iteration ? `${workerId}_${iteration}` : workerId;
      const hasError = Boolean(evt.data.error || evt.data.has_error);
      const toolsCreated = (evt.data.tools_created as string[]) ?? [];
      const nodeUpdate: Partial<Node['data']> = {
        status: hasError ? 'error' : 'complete',
        confidence: evt.data.confidence as number | undefined,
        outputs: evt.data.result as Record<string, unknown> | undefined,
        error: evt.data.error as string | undefined,
        tools_created: toolsCreated,
      };
      // Attach eval scores if present
      if (typeof evt.data.eval_score === 'number') {
        nodeUpdate.eval_score = evt.data.eval_score as number;
        nodeUpdate.eval_action = (evt.data.eval_action as string) ?? '';
        nodeUpdate.eval_metrics = (evt.data.eval_metrics as Array<{name: string; score: number; weight: number}>) ?? [];
      }
      // Try iteration-qualified ID first, fall back to plain workerId for backwards compat
      const nodeExists = store.graphNodes.some((n) => n.id === workerNodeId);
      store.updateGraphNode(nodeExists ? workerNodeId : workerId, nodeUpdate);
      // Propagate eval score to parent iteration node
      if (typeof evt.data.eval_score === 'number') {
        const iterNum = evt.data.iteration as string | undefined;
        if (iterNum) {
          const iterNodeId = `iter_${iterNum.replace(/^.*_/, '')}`;
          store.updateGraphNode(iterNodeId, {
            eval_score: evt.data.eval_score as number,
            eval_action: (evt.data.eval_action as string) ?? '',
            eval_metrics: (evt.data.eval_metrics as Array<{name: string; score: number; weight: number}>) ?? [],
          });
        }
      }
      // Always show worker results (errors always, success in verbose or summarized)
      if (hasError) {
        store.addOutputBlock({
          type: 'error',
          content: `Worker \`${workerId.slice(0, 8)}\` failed: ${evt.data.error}`,
          title: 'Worker Error',
        });
      } else if (isVerbose) {
        const resultData = evt.data.result ?? evt.data.output ?? evt.data.answer ?? evt.data;
        store.addOutputBlock({
          type: 'json',
          content: JSON.stringify(resultData, null, 2),
          title: `Worker ${workerId.slice(0, 8)} (confidence: ${evt.data.confidence ?? '?'})`,
        });
      }
      // Show eval score for this worker as markdown
      if (typeof evt.data.eval_score === 'number') {
        const ePct = Math.round((evt.data.eval_score as number) * 100);
        const eIcon = ePct >= 75 ? '🟢' : ePct >= 50 ? '🟡' : '🔴';
        let eMd = `### ${eIcon} Worker Eval: ${ePct}% — ${((evt.data.eval_action as string) ?? '').replace(/_/g, ' ')}\n`;
        const eMetrics = evt.data.eval_metrics as Array<{ name: string; score: number; weight: number }> | undefined;
        if (eMetrics && eMetrics.length > 0) {
          eMd += '\n| Metric | Score | Weight |\n|--------|------:|-------:|\n';
          for (const m of eMetrics) {
            eMd += `| ${m.score >= 0.65 ? '✅' : m.score >= 0.4 ? '⚠️' : '❌'} ${m.name} | ${Math.round(m.score * 100)}% | ${m.weight} |\n`;
          }
        }
        store.addOutputBlock({ type: 'markdown', content: eMd, title: `Eval: ${workerId.slice(0, 8)}` });
      }
      break;
    }

    // ----- Agent complete -----
    case 'agent.complete': {
      const id = nodeIdFromEvent(evt);
      store.updateGraphNode(id, {
        status: 'complete',
        confidence: evt.data.confidence as number | undefined,
        outputs: evt.data.result as Record<string, unknown> | undefined,
      });
      if (evt.data.result) {
        store.addOutputBlock({
          type: 'json',
          content: JSON.stringify(evt.data.result, null, 2),
          title: (evt.data.agent_name as string) ?? 'Agent Result',
        });
      }
      break;
    }

    // ----- Tool calls -----
    case 'tool.call': {
      const toolName = (evt.data.tool_name as string) ?? (evt.data.tool as string) ?? 'Tool';
      const callerId = (evt.data.worker_id as string) ?? (evt.data.agent_id as string) ?? (evt.data.caller_id as string) ?? '';
      const callIndex = evt.data.call_index as number | undefined;
      const iteration = (evt.data.iteration as string) ?? '';
      // Use iteration + callIndex for unique IDs; fall back to timestamp to avoid collisions
      const uniqueSuffix = callIndex != null ? String(callIndex) : `t${Date.now()}_${store.graphNodes.length}`;
      const iterPrefix = iteration ? `${iteration}_` : '';
      const toolId = `tool-${iterPrefix}${callerId}-${toolName}-${uniqueSuffix}`;
      const toolOutput = (evt.data.output as string) ?? '';
      const toolError = (evt.data.error as string) ?? '';
      const toolArgs = evt.data.arguments as Record<string, unknown> | undefined;
      // Resolve caller node ID: try iteration-qualified first
      const callerNodeId = iteration ? `${callerId}_${iteration}` : callerId;
      const callerExists = store.graphNodes.some((n) => n.id === callerNodeId);
      const resolvedCallerId = callerExists ? callerNodeId : callerId;

      store.addGraphNode({
        id: toolId,
        type: 'default',
        position: { x: 450, y: store.graphNodes.length * 120 },
        data: {
          label: toolName,
          status: (evt.data.ok === false) ? 'error' : 'complete',
          nodeType: 'toolCall',
          arguments: toolArgs,
          outputs: toolOutput ? { output: toolOutput } : undefined,
          error: toolError || undefined,
          details: evt.data,
        },
      });
      if (resolvedCallerId) {
        store.addGraphEdge({
          id: `e-${resolvedCallerId}-${toolId}`,
          source: resolvedCallerId,
          target: toolId,
        });
      }
      // Show code execution blocks with syntax highlighting
      if (toolName === 'code.execute' && toolArgs?.code && typeof toolArgs.code === 'string') {
        store.addOutputBlock({
          type: 'code',
          content: toolArgs.code as string,
          language: 'python',
          title: `Code Execution${evt.data.ok === false ? ' (FAILED)' : ''}`,
        });
        if (toolOutput) {
          store.addOutputBlock({
            type: 'code',
            content: toolOutput,
            language: 'text',
            title: 'Output',
          });
          // Detect PNG/image file paths in stdout and show them inline
          const imgPathPattern = /(\/tmp\/[^\s'"]+\.(?:png|jpg|jpeg|gif|svg))/gi;
          const imgMatches = toolOutput.match(imgPathPattern);
          if (imgMatches) {
            for (const imgPath of [...new Set(imgMatches)]) {
              const url = `/api/files/serve?path=${encodeURIComponent(imgPath)}`;
              store.addOutputBlock({
                type: 'image',
                content: url,
                title: imgPath.split('/').pop() ?? 'Chart',
              });
            }
          }
        }
        if (toolError) {
          store.addOutputBlock({
            type: 'error',
            content: toolError,
            title: 'Execution Error',
          });
        }
      } else if (toolName === 'file.write' && evt.data.ok !== false) {
        // Detect file.write of image files and show them inline
        const writePath = (toolArgs?.path as string) ?? '';
        if (/\.(png|jpg|jpeg|gif|svg)$/i.test(writePath)) {
          const url = `/api/files/serve?path=${encodeURIComponent(writePath)}`;
          store.addOutputBlock({
            type: 'image',
            content: url,
            title: writePath.split('/').pop() ?? 'Image',
          });
        } else if (isVerbose) {
          store.addOutputBlock({
            type: 'code',
            content: `${toolName}(${callerId.slice(0, 8)}) → OK`,
            title: 'Tool Call',
          });
        }
      } else if (isVerbose) {
        store.addOutputBlock({
          type: 'code',
          content: `${toolName}(${callerId.slice(0, 8)})${evt.data.ok === false ? ' → FAILED' : ' → OK'}`,
          title: 'Tool Call',
        });
      }
      break;
    }

    case 'tool.result': {
      const toolId = nodeIdFromEvent(evt);
      store.updateGraphNode(toolId, {
        status: 'complete',
        outputs: evt.data,
      });
      break;
    }

    // ----- Budget -----
    case 'budget.update': {
      // Map both flat format and nested format from watcher
      const d = evt.data;
      const budgetUpdate: Partial<BudgetState> = {};

      if (typeof d.loops_used === 'number') budgetUpdate.loops_used = d.loops_used;
      if (typeof d.tokens_used === 'number') budgetUpdate.tokens_used = d.tokens_used;
      if (typeof d.workers_used === 'number') budgetUpdate.workers_used = d.workers_used;

      // Nested format from budget_snapshot.json
      const loops = d.loops as Record<string, number> | undefined;
      const tokens = d.tokens as Record<string, number> | undefined;
      const workers = d.workers as Record<string, number> | undefined;
      const wallTime = d.wall_time as Record<string, number> | undefined;
      const toolCalls = d.tool_calls as Record<string, number> | undefined;

      if (loops) {
        if (typeof loops.used === 'number') budgetUpdate.loops_used = loops.used;
        if (typeof loops.max === 'number') budgetUpdate.loops_max = loops.max;
      }
      if (tokens) {
        if (typeof tokens.consumed === 'number') budgetUpdate.tokens_used = tokens.consumed;
        if (typeof tokens.max === 'number') budgetUpdate.tokens_max = tokens.max;
      }
      if (workers) {
        if (typeof workers.spawned === 'number') budgetUpdate.workers_used = workers.spawned;
        if (typeof workers.max === 'number') budgetUpdate.workers_max = workers.max;
      }
      if (wallTime) {
        if (typeof wallTime.elapsed_s === 'number') budgetUpdate.wall_time_ms = wallTime.elapsed_s * 1000;
        if (typeof wallTime.max_s === 'number') budgetUpdate.wall_time_max_ms = wallTime.max_s * 1000;
      }
      if (toolCalls) {
        if (typeof toolCalls.used === 'number') budgetUpdate.tool_calls_used = toolCalls.used;
        if (typeof toolCalls.max === 'number') budgetUpdate.tool_calls_max = toolCalls.max;
      }

      if (Object.keys(budgetUpdate).length > 0) {
        store.updateBudget(budgetUpdate);
      }
      break;
    }

    // ----- Run complete -----
    case 'run.complete': {
      const status = (evt.data.status as string) ?? 'complete';
      const isError = status === 'error' || status === 'failed';
      const resultObj = evt.data.result as Record<string, unknown> | undefined;

      // Detect if this is the file-watcher completion (has total_iterations)
      // vs the runner-service completion (has result.result with actual content)
      const isFileWatcherEvent = !resultObj || ('total_iterations' in evt.data && !('_evaluation' in (resultObj ?? {})));

      // Update manager and task root nodes
      store.updateGraphNode('manager', { status: isError ? 'error' : 'complete' });
      store.updateGraphNode('task_root', { status: isError ? 'error' : 'complete' });

      // Update run status and session status in sidebar
      const completedSessionId = get().currentSessionId;
      set((prev) => ({
        runStatus: isError ? 'error' : 'complete',
        activePanel: 'output',
        sessions: completedSessionId
          ? prev.sessions.map((sess) =>
              sess.id === completedSessionId
                ? { ...sess, status: (isError ? 'failed' : 'complete') as Session['status'], last_run_status: isError ? 'failed' : 'complete' }
                : sess,
            )
          : prev.sessions,
      }));

      if (isFileWatcherEvent) {
        break;
      }

      if (isError && resultObj) {
        store.addOutputBlock({
          type: 'error',
          content: (resultObj.error as string) ?? JSON.stringify(resultObj, null, 2),
          title: 'Error',
        });
      } else if (resultObj) {
        for (const block of resultToOutputBlocks(resultObj, 'Final Result')) {
          store.addOutputBlock(block);
        }
      }
      // Load full graph from backend and refresh history
      store.loadRunGraph();
      store.loadHistory();

      // Auto-add finding to experiment memory
      {
        const sessionId = get().currentSessionId;
        const runId = get().currentRunId;
        if (sessionId && evt.data.result) {
          const resultStr = typeof evt.data.result === 'string'
            ? (evt.data.result as string)
            : JSON.stringify(evt.data.result, null, 2);
          const summary = resultStr.slice(0, 500);
          api.addMemoryEntry(sessionId, {
            type: isError ? 'observation' : 'finding',
            content: isError
              ? `Run ${(runId ?? '').slice(0, 8)} failed: ${summary}`
              : `Run ${(runId ?? '').slice(0, 8)}: ${summary}`,
            source: 'agent',
            run_id: runId ?? undefined,
          }).then((entry) => {
            set((s) => ({ experimentMemory: [entry, ...s.experimentMemory] }));
          }).catch(() => {});
        }
      }
      break;
    }

    // ----- Errors & logs -----
    case 'error': {
      store.addOutputBlock({
        type: 'error',
        content: (evt.data.message as string) ?? (evt.data.error as string) ?? 'Unknown error',
        title: 'Error',
      });
      break;
    }

    case 'log': {
      store.addOutputBlock({
        type: 'markdown',
        content: (evt.data.message as string) ?? '',
        title: 'Log',
      });
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// Session cache helpers
// ---------------------------------------------------------------------------

const MAX_CACHED_SESSIONS = 10;

/** Snapshot current per-session state from the store into a CachedSessionState. */
function snapshotSession(s: WorkflowStore): CachedSessionState | null {
  if (!s.currentSessionId) return null;
  return {
    sessionId: s.currentSessionId,
    currentRunId: s.currentRunId,
    runStatus: s.runStatus,
    events: s.events,
    graphNodes: s.graphNodes,
    graphEdges: s.graphEdges,
    outputBlocks: s.outputBlocks,
    budget: { ...s.budget },
    sessionHistory: s.sessionHistory,
    experimentMemory: s.experimentMemory,
    config: { ...s.config },
    runHistory: s.runHistory,
    selectedNodeId: s.selectedNodeId,
  };
}

/** Restore cached session state into a partial store update. */
function restoreFromCache(cached: CachedSessionState): Partial<WorkflowStore> {
  return {
    currentSessionId: cached.sessionId,
    currentRunId: cached.currentRunId,
    runStatus: cached.runStatus,
    events: cached.events,
    graphNodes: cached.graphNodes,
    graphEdges: cached.graphEdges,
    outputBlocks: cached.outputBlocks,
    budget: cached.budget,
    sessionHistory: cached.sessionHistory,
    experimentMemory: cached.experimentMemory,
    config: cached.config,
    runHistory: cached.runHistory,
    selectedNodeId: cached.selectedNodeId,
  };
}

/** Evict oldest entries from cache map to stay within size limit. */
function evictCache(cache: Map<string, CachedSessionState>, maxSize: number) {
  while (cache.size > maxSize) {
    const firstKey = cache.keys().next().value;
    if (firstKey) cache.delete(firstKey);
  }
}

/** Route a WebSocket event to a background (non-active) session's cache. */
function routeBackgroundEvent(
  event: RunEvent,
  sessionId: string,
  get: () => WorkflowStore,
  set: (partial: Partial<WorkflowStore> | ((s: WorkflowStore) => Partial<WorkflowStore>)) => void,
) {
  const s = get();
  const cached = s._sessionCache.get(sessionId);
  if (!cached) return;

  // Append event
  cached.events = [...cached.events, event];

  // Update status on run lifecycle events
  if (event.type === 'run.complete') {
    const status = (event.data.status as string) ?? 'complete';
    cached.runStatus = (status === 'error' || status === 'failed') ? 'error' : 'complete';
  } else if (event.type === 'error') {
    cached.runStatus = 'error';
  }

  // Update budget
  if (event.type === 'budget.update') {
    const d = event.data;
    if (typeof d.loops_used === 'number') cached.budget.loops_used = d.loops_used;
    if (typeof d.tokens_used === 'number') cached.budget.tokens_used = d.tokens_used;
    if (typeof d.workers_used === 'number') cached.budget.workers_used = d.workers_used;
  }

  // Update session list status on completion
  if (event.type === 'run.complete' || event.type === 'error') {
    const runStatus = event.type === 'error' ? 'failed' : ((event.data.status as string) ?? 'complete');
    set((prev) => ({
      sessions: prev.sessions.map((sess) =>
        sess.id === sessionId
          ? { ...sess, status: (runStatus === 'error' || runStatus === 'failed') ? 'failed' as const : 'complete' as const, last_run_status: runStatus }
          : sess,
      ),
    }));
  }
}

// ---------------------------------------------------------------------------
// Store creation
// ---------------------------------------------------------------------------

export const useWorkflowStore = create<WorkflowStore>((set, get) => ({
  // -- Config ---------------------------------------------------------------
  config: { ...DEFAULT_CONFIG },
  updateConfig: (partial) =>
    set((s) => ({ config: { ...s.config, ...partial } })),

  // -- Run state ------------------------------------------------------------
  currentRunId: null,
  runStatus: 'idle',
  events: [],
  addEvent: (event) => {
    // Deduplicate events by type+seq to handle replayed buffer
    const existing = get().events;
    const isDupe = existing.some(
      (e) => e.type === event.type && e.seq === event.seq && e.timestamp === event.timestamp,
    );
    if (isDupe) return;
    set((s) => ({ events: [...s.events, event] }));
    processEvent(event, get, set);
  },

  // -- Graph ----------------------------------------------------------------
  graphNodes: [],
  graphEdges: [],
  addGraphNode: (node) =>
    set((s) => {
      // Avoid duplicate IDs
      if (s.graphNodes.some((n) => n.id === node.id)) return s;
      return { graphNodes: [...s.graphNodes, node] };
    }),
  addGraphEdge: (edge) =>
    set((s) => {
      if (s.graphEdges.some((e) => e.id === edge.id)) return s;
      return { graphEdges: [...s.graphEdges, edge] };
    }),
  updateGraphNode: (id, data) =>
    set((s) => ({
      graphNodes: s.graphNodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, ...data } } : n,
      ),
    })),
  selectedNodeId: null,
  selectNode: (id) =>
    set({ selectedNodeId: id, inspectorOpen: id !== null }),
  loadRunGraph: async (runId) => {
    const rid = runId ?? get().currentRunId;
    if (!rid) return;
    try {
      const graph = await api.getRunGraph(rid);
      // Only replace if backend returned actual nodes — don't discard
      // real-time nodes with an empty response
      if (!graph.nodes || graph.nodes.length === 0) return;
      // Map backend nodes to ReactFlow Node format
      const nodes: Node[] = graph.nodes.map((n, i) => ({
        id: n.id,
        type: 'default',
        position: (n as unknown as Record<string, unknown>).position as { x: number; y: number } ?? { x: 0, y: i * 120 },
        data: { ...n.data, nodeType: n.type },
      }));
      const edges: Edge[] = graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
      }));
      set({ graphNodes: nodes, graphEdges: edges });
    } catch {
      // silently ignore
    }
  },

  // -- Output ---------------------------------------------------------------
  outputBlocks: [],
  addOutputBlock: (block) =>
    set((s) => ({ outputBlocks: [...s.outputBlocks, block] })),

  // -- Run selection --------------------------------------------------------
  selectedRunId: null,
  selectRun: (runId) => set({ selectedRunId: runId, selectedRunBlocks: [] }),
  selectedRunBlocks: [],
  loadRunBlocks: async (runId: string) => {
    try {
      const run = await api.getRun(runId);
      const events = (run.events && run.events.length > 0)
        ? run.events
        : await api.getRunEvents(runId).catch(() => [] as Array<{type: string; data: Record<string, unknown>}>);
      const blocks: OutputBlock[] = [];

      blocks.push({
        type: 'markdown',
        content: `**Run started** — ${run.model}`,
        title: 'Run',
      });

      for (const evt of events) {
        const d = evt.data as Record<string, unknown>;
        switch (evt.type) {
          case 'iteration.start':
            blocks.push({ type: 'markdown', content: `**Iteration ${d.iteration ?? '?'}**`, title: 'Iteration' });
            break;
          case 'iteration.decision': {
            const decision = (d.decision as string) ?? '';
            const reasoning = (d.reasoning as string) ?? '';
            const conf = d.confidence;
            blocks.push(reasoning
              ? { type: 'markdown', content: `**Decision: ${decision}** (confidence: ${conf ?? '?'})\n\n${reasoning}`, title: `Iteration ${d.iteration ?? '?'}` }
              : { type: 'json', content: JSON.stringify(d, null, 2), title: `Iteration ${d.iteration ?? '?'}` }
            );
            break;
          }
          case 'worker.spawn':
            blocks.push({ type: 'markdown', content: `**Worker spawned:** \`${((d.worker_id as string) ?? '?').slice(0, 8)}\`\n\n${((d.instructions as string) ?? '').slice(0, 500)}`, title: 'Worker' });
            break;
          case 'worker.complete': {
            const hasErr = Boolean(d.error || d.has_error);
            blocks.push({
              type: hasErr ? 'error' : 'json',
              content: hasErr ? `Worker failed: ${d.error}` : JSON.stringify(d.result ?? d, null, 2),
              title: `Worker ${((d.worker_id as string) ?? '?').slice(0, 8)}`,
            });
            // Show worker eval score as markdown
            if (typeof d.eval_score === 'number') {
              const ePct = Math.round((d.eval_score as number) * 100);
              const eIcon = ePct >= 75 ? '🟢' : ePct >= 50 ? '🟡' : '🔴';
              let eMd = `### ${eIcon} Worker Eval: ${ePct}% — ${((d.eval_action as string) ?? '').replace(/_/g, ' ')}\n`;
              const eMetrics = d.eval_metrics as Array<{ name: string; score: number; weight: number }> | undefined;
              if (eMetrics && eMetrics.length > 0) {
                eMd += '\n| Metric | Score | Weight |\n|--------|------:|-------:|\n';
                for (const m of eMetrics) {
                  eMd += `| ${m.score >= 0.65 ? '✅' : m.score >= 0.4 ? '⚠️' : '❌'} ${m.name} | ${Math.round(m.score * 100)}% | ${m.weight} |\n`;
                }
              }
              blocks.push({ type: 'markdown', content: eMd, title: `Eval: ${((d.worker_id as string) ?? '?').slice(0, 8)}` });
            }
            break;
          }
          case 'tool.call': {
            const toolName = (d.tool_name as string) ?? (d.tool as string) ?? 'Tool';
            const toolArgs = d.arguments as Record<string, unknown> | undefined;
            const toolOutput = (d.output as string) ?? '';
            const toolError = (d.error as string) ?? '';

            if (toolName === 'code.execute' && toolArgs?.code && typeof toolArgs.code === 'string') {
              blocks.push({
                type: 'code',
                content: toolArgs.code as string,
                language: 'python',
                title: `Code Execution${d.ok === false ? ' (FAILED)' : ''}`,
              });
              if (toolOutput) {
                blocks.push({ type: 'code', content: toolOutput, language: 'text', title: 'Output' });
                // Detect image file paths in output
                const imgPattern = /(\/tmp\/[^\s'"]+\.(?:png|jpg|jpeg|gif|svg))/gi;
                const imgMatches = toolOutput.match(imgPattern);
                if (imgMatches) {
                  for (const imgPath of [...new Set(imgMatches)]) {
                    blocks.push({
                      type: 'image',
                      content: `/api/files/serve?path=${encodeURIComponent(imgPath)}`,
                      title: imgPath.split('/').pop() ?? 'Chart',
                    });
                  }
                }
              }
              if (toolError) {
                blocks.push({ type: 'error', content: toolError, title: 'Execution Error' });
              }
            } else if (toolName === 'file.write' && d.ok !== false) {
              const writePath = (toolArgs?.path as string) ?? '';
              if (/\.(png|jpg|jpeg|gif|svg)$/i.test(writePath)) {
                blocks.push({
                  type: 'image',
                  content: `/api/files/serve?path=${encodeURIComponent(writePath)}`,
                  title: writePath.split('/').pop() ?? 'Image',
                });
              }
            }
            break;
          }
          case 'delegation.start': {
            const model = (d.model as string) ?? '?';
            const depth = (d.depth as number) ?? 1;
            blocks.push({ type: 'markdown', content: `**Sub-delegation** (depth ${depth}, model: ${model})`, title: 'Delegation' });
            break;
          }
          case 'run.complete': {
            const status = (d.status as string) ?? 'complete';
            if (status === 'error' || status === 'failed') {
              blocks.push({ type: 'error', content: (d.error as string) ?? 'Run failed', title: 'Run Error' });
            }
            break;
          }
          case 'error':
            blocks.push({ type: 'error', content: (d.message as string) ?? (d.error as string) ?? 'Unknown error', title: 'Error' });
            break;
        }
      }

      // Add final result
      if (run.result) {
        const r = run.result as Record<string, unknown>;
        const isErr = r.status === 'error' || r.status === 'failed';
        if (isErr) {
          const resultData = r.result as Record<string, unknown> | undefined;
          blocks.push({ type: 'error', content: (resultData?.error as string) ?? JSON.stringify(r, null, 2), title: 'Error' });
        } else {
          // Pass the full result (r) so _evaluation is accessible
          for (const block of resultToOutputBlocks(r, 'Final Result')) {
            blocks.push(block);
          }
        }
      }

      set({ selectedRunBlocks: blocks });
    } catch {
      set({ selectedRunBlocks: [] });
    }
  },

  // -- Budget ---------------------------------------------------------------
  budget: { ...DEFAULT_BUDGET },
  updateBudget: (partial) =>
    set((s) => ({ budget: { ...s.budget, ...partial } })),

  // -- UI state -------------------------------------------------------------
  activePanel: 'protocol',
  setActivePanel: (panel) => set({ activePanel: panel }),
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  inspectorOpen: false,
  toggleInspector: () => set((s) => ({ inspectorOpen: !s.inspectorOpen })),

  // -- Skills & Tools -------------------------------------------------------
  skills: [],
  mcpServers: [],

  // -- History --------------------------------------------------------------
  runHistory: [],
  loadHistory: async () => {
    try {
      const sessionId = get().currentSessionId;
      if (sessionId) {
        // Experiment-scoped: only show runs for current experiment
        const detail = await api.getSession(sessionId);
        set({ runHistory: detail.runs });
      } else {
        // No experiment selected: show all runs
        const history = await api.listRuns();
        set({ runHistory: history });
      }
    } catch {
      // silently ignore -- backend may be down
    }
  },

  // -- Actions --------------------------------------------------------------
  startRun: async () => {
    const state = get();
    if (state.runStatus === 'running') return;

    // Reset run state
    set({
      runStatus: 'running',
      events: [],
      graphNodes: [],
      graphEdges: [],
      outputBlocks: [],
      selectedRunId: null,
      selectedRunBlocks: [],
      budget: {
        ...DEFAULT_BUDGET,
        loops_max: state.config.max_loops,
        tokens_max: state.config.max_total_tokens,
        workers_max: state.config.max_total_workers,
        wall_time_max_ms: state.config.max_wall_time * 1000,
        tool_calls_max: state.config.max_tool_calls,
      },
      selectedNodeId: null,
      activePanel: 'protocol',
    });

    try {
      // Upload attached files and inject paths into config
      let uploadedPaths: string[] = [];
      if (state.attachedFiles.length > 0) {
        const result = await api.uploadFiles(state.attachedFiles);
        uploadedPaths = result.paths;
      }

      // Auto-create session if none exists
      let sessionId = state.currentSessionId;
      if (!sessionId) {
        try {
          const title =
            state.config.task.slice(0, 60) ||
            `Session ${new Date().toLocaleString()}`;
          const session = await api.createSession(title);
          sessionId = session.id;
          set((s) => ({
            currentSessionId: session.id,
            sessions: [session, ...s.sessions],
          }));
        } catch {
          // Non-critical: continue without session
        }
      }

      // Build config for the run (clean empty optional fields)
      const runConfig = {
        ...state.config,
        output_dir: state.config.output_dir?.trim() || '',
        input_files: uploadedPaths,
      } as WorkflowConfig;

      // Pre-flight: check API key is available for the selected model
      try {
        const preflight = await api.preflightCheck(runConfig);
        if (!preflight.ok) {
          set({ runStatus: 'error' });
          const store = get() as ReturnType<typeof useWorkflowStore.getState>;
          store.addOutputBlock({
            type: 'error',
            content: preflight.message
              ?? `No API key found for ${preflight.provider}. Add **${preflight.required_key}** in Settings → API Keys.`,
            title: 'Missing API Key',
          });
          return;
        }
      } catch {
        // Preflight endpoint may not exist on older backends — continue anyway
      }

      // Start the run (in session context if available)
      let run_id: string;
      if (sessionId) {
        const result = await api.startRunInSession(sessionId, runConfig);
        run_id = result.run_id;
      } else {
        const result = await api.startRun(runConfig);
        run_id = result.run_id;
      }
      set({ currentRunId: run_id });

      // Update session status to 'running' in sidebar
      if (sessionId) {
        set((prev) => ({
          sessions: prev.sessions.map((sess) =>
            sess.id === sessionId
              ? { ...sess, status: 'running' as const, last_run_status: 'running' }
              : sess,
          ),
        }));
      }

      // Open WebSocket — route events to active store or background cache
      const runSessionId = get().currentSessionId;
      const conn = connectToRun(run_id, (event) => {
        const current = get();
        if (current.currentSessionId === runSessionId) {
          // Active session — process normally
          current.addEvent(event);
          if (
            (event.type === 'run.complete' || event.type === 'error') &&
            current.currentSessionId
          ) {
            const sid = current.currentSessionId!;
            api
              .getSessionHistory(sid)
              .then((history) => set({ sessionHistory: history }))
              .catch(() => {});
            api
              .listSessions()
              .then((sessions) => set({ sessions }))
              .catch(() => {});
          }
        } else if (runSessionId) {
          // Session switched — route to background cache
          routeBackgroundEvent(event, runSessionId, get, set);
        }
      }, {
        onStateChange: (ws) => {
          if (get().currentSessionId === runSessionId) set({ _wsStatus: ws });
        },
      });
      // Store in WS pool for multi-experiment support
      if (runSessionId) {
        get()._wsPool.set(run_id, conn);
        get()._runToSession.set(run_id, runSessionId);
      }
      set({ _wsConnection: conn });
    } catch (err) {
      set({
        runStatus: 'error',
        outputBlocks: [
          {
            type: 'error',
            content:
              err instanceof Error ? err.message : 'Failed to start run',
            title: 'Start Error',
          },
        ],
      });
    }
  },

  stopRun: async () => {
    const state = get();
    if (!state.currentRunId) return;

    try {
      await api.stopRun(state.currentRunId);
    } catch {
      // best-effort
    }

    // Clean up from WS pool
    const runId = state.currentRunId;
    const pooledWs = state._wsPool.get(runId);
    if (pooledWs) {
      pooledWs.close();
      state._wsPool.delete(runId);
    }
    state._runToSession.delete(runId);

    state._wsConnection?.close();
    set({
      runStatus: 'complete',
      _wsConnection: null,
      _wsStatus: 'closed',
    });
  },

  reset: () => {
    const state = get();
    state._wsConnection?.close();
    // Close all pooled WebSocket connections
    for (const ws of state._wsPool.values()) {
      ws.close();
    }
    state._wsPool.clear();
    state._runToSession.clear();
    state._sessionCache.clear();
    set({
      currentRunId: null,
      runStatus: 'idle',
      events: [],
      graphNodes: [],
      graphEdges: [],
      outputBlocks: [],
      budget: { ...DEFAULT_BUDGET },
      selectedNodeId: null,
      _wsConnection: null,
      _wsStatus: 'closed',
      attachedFiles: [],
    });
  },

  // -- Files ----------------------------------------------------------------
  attachedFiles: [],
  addFiles: (files) =>
    set((s) => ({ attachedFiles: [...s.attachedFiles, ...files] })),
  removeFile: (index) =>
    set((s) => ({
      attachedFiles: s.attachedFiles.filter((_, i) => i !== index),
    })),

  // -- Sessions -------------------------------------------------------------
  currentSessionId: null,
  sessions: [],
  sessionHistory: [],

  createSession: async (title) => {
    try {
      const sessionTitle =
        title ?? `Experiment ${new Date().toLocaleString()}`;
      const session = await api.createSession(sessionTitle);

      // Snapshot current session state to cache (preserves background WS)
      const prev = get();
      const snapshot = snapshotSession(prev);
      if (snapshot) {
        prev._sessionCache.set(snapshot.sessionId, snapshot);
        evictCache(prev._sessionCache, MAX_CACHED_SESSIONS);
      }

      // If the current session has a running WS, keep it alive in the pool
      if (prev._wsConnection && prev.currentRunId) {
        prev._wsPool.set(prev.currentRunId, prev._wsConnection);
        prev._runToSession.set(prev.currentRunId, prev.currentSessionId!);
      }

      set((s) => ({
        currentSessionId: session.id,
        sessions: [session, ...s.sessions],
        sessionHistory: [],
        outputBlocks: [],
        events: [],
        graphNodes: [],
        graphEdges: [],
        experimentMemory: [],
        // Reset run state so the UI is fully clean
        currentRunId: null,
        runStatus: 'idle',
        budget: { ...DEFAULT_BUDGET },
        selectedNodeId: null,
        attachedFiles: [],
        config: { ...DEFAULT_CONFIG, model: s.config.model, api_key: s.config.api_key, worker_model: s.config.worker_model },
        _wsConnection: null,
        _wsStatus: 'closed',
      }));
    } catch {
      // silently ignore
    }
  },

  loadSessions: async () => {
    try {
      const sessions = await api.listSessions();
      set({ sessions });
      // Auto-create a first experiment so the user can start immediately
      // (only if no session was already restored by loadPersistedSettings)
      if (sessions.length === 0 && !get().currentSessionId) {
        const store = get() as ReturnType<typeof useWorkflowStore.getState>;
        await store.createSession('Experiment 1');
      }
    } catch {
      // silently ignore -- backend may be down
    }
  },

  selectSession: async (sessionId) => {
    const s = get();
    // Don't re-select the current session
    if (s.currentSessionId === sessionId) return;

    // Snapshot current session state into cache before switching
    const snapshot = snapshotSession(s);
    if (snapshot) {
      s._sessionCache.set(snapshot.sessionId, snapshot);
      evictCache(s._sessionCache, MAX_CACHED_SESSIONS);
    }

    // If the current session has a running WS, rewire it to background mode
    if (s._wsConnection && s.currentRunId) {
      const bgRunId = s.currentRunId;
      const bgSessionId = s.currentSessionId!;
      // The WS stays alive in the pool — its events will update the cache
      // via the onEvent callback that was set up in startRun
      s._wsPool.set(bgRunId, s._wsConnection);
      s._runToSession.set(bgRunId, bgSessionId);
    }

    // Check if the target session is already in cache
    const cached = s._sessionCache.get(sessionId);
    if (cached) {
      // Remove from cache (it becomes the active session)
      s._sessionCache.delete(sessionId);
      // Restore from cache — instant, no API call
      const restored = restoreFromCache(cached);
      // If the restored session has a running run, reconnect _wsConnection
      let wsConn: WebSocketConnection | null = null;
      let wsStatus: 'connecting' | 'open' | 'closed' | 'error' = 'closed';
      if (cached.currentRunId && cached.runStatus === 'running') {
        const pooledWs = s._wsPool.get(cached.currentRunId);
        if (pooledWs) {
          wsConn = pooledWs;
          wsStatus = pooledWs.readyState() === WebSocket.OPEN ? 'open' : 'connecting';
        }
      }
      set({
        ...restored,
        _wsConnection: wsConn,
        _wsStatus: wsStatus,
      });
      return;
    }

    // Not cached — fetch from API
    try {
      const full = await api.getSessionFull(sessionId);

      // Restore session config
      const settings = full.session.settings ?? {};
      const configUpdate: Partial<WorkflowConfig> = {};
      if (Object.keys(settings).length > 0) {
        Object.assign(configUpdate, settings);
      }

      // Find the last run for status and graph
      const lastRun = full.runs.length > 0 ? full.runs[full.runs.length - 1] : null;
      const lastRunId = lastRun?.run_id ?? null;
      const runStatus = lastRun
        ? (lastRun.status === 'error' || lastRun.status === 'failed' ? 'error' as const
          : lastRun.status === 'running' ? 'running' as const
          : 'complete' as const)
        : 'idle' as const;

      // Set last task
      if (lastRun) {
        configUpdate.task = lastRun.task;
      }

      // Rebuild output blocks from ALL runs' events
      const outputBlocks: OutputBlock[] = [];
      const allEvents: RunEvent[] = [];
      for (const run of full.runs) {
        // Add task header
        outputBlocks.push({
          type: 'markdown',
          content: `**Run started** — ${run.model}`,
          title: 'Run',
        });

        // Replay events for output blocks
        for (const evt of run.events) {
          allEvents.push(evt as unknown as RunEvent);
          const d = evt.data;
          switch (evt.type) {
            case 'iteration.start':
              outputBlocks.push({
                type: 'markdown',
                content: `**Iteration ${d.iteration ?? '?'}**`,
                title: 'Iteration',
              });
              break;
            case 'iteration.decision': {
              const decision = (d.decision as string) ?? '';
              const reasoning = (d.reasoning as string) ?? '';
              const conf = d.confidence;
              if (reasoning) {
                outputBlocks.push({
                  type: 'markdown',
                  content: `**Decision: ${decision}** (confidence: ${conf ?? '?'})\n\n${reasoning}`,
                  title: `Iteration ${d.iteration ?? '?'}`,
                });
              } else {
                outputBlocks.push({
                  type: 'json',
                  content: JSON.stringify(d, null, 2),
                  title: `Iteration ${d.iteration ?? '?'}`,
                });
              }
              break;
            }
            case 'worker.spawn':
              outputBlocks.push({
                type: 'markdown',
                content: `**Worker spawned:** \`${((d.worker_id as string) ?? '?').slice(0, 8)}\`\n\n${((d.instructions as string) ?? '').slice(0, 500)}`,
                title: 'Worker',
              });
              break;
            case 'worker.complete': {
              const hasErr = Boolean(d.error || d.has_error);
              outputBlocks.push({
                type: hasErr ? 'error' : 'json',
                content: hasErr
                  ? `Worker failed: ${d.error}`
                  : JSON.stringify(d.result ?? d, null, 2),
                title: `Worker ${((d.worker_id as string) ?? '?').slice(0, 8)}`,
              });
              break;
            }
            case 'error':
              outputBlocks.push({
                type: 'error',
                content: (d.message as string) ?? (d.error as string) ?? 'Unknown error',
                title: 'Error',
              });
              break;
          }
        }

        // Add final result
        if (run.result) {
          const r = run.result;
          const isErr = r.status === 'error' || r.status === 'failed';
          if (isErr) {
            const resultData = r.result as Record<string, unknown> | undefined;
            outputBlocks.push({
              type: 'error',
              content: (resultData?.error as string) ?? JSON.stringify(r, null, 2),
              title: 'Error',
            });
          } else {
            for (const block of resultToOutputBlocks(r, 'Final Result')) {
              outputBlocks.push(block);
            }
          }
        }
      }

      // Build graph from last run's backend data, or reconstruct from events
      let graphNodes: Node[] = [];
      let graphEdges: Edge[] = [];
      if (lastRun?.graph?.nodes?.length) {
        graphNodes = lastRun.graph.nodes.map((n: Record<string, unknown>, i: number) => ({
          id: n.id as string,
          type: 'default',
          position: (n.position as { x: number; y: number }) ?? { x: 0, y: i * 120 },
          data: { ...(n.data as Record<string, unknown>), nodeType: n.type as string },
        }));
        graphEdges = lastRun.graph.edges.map((e: Record<string, unknown>) => ({
          id: e.id as string,
          source: e.source as string,
          target: e.target as string,
        }));
      } else if (lastRun && allEvents.length > 0) {
        // No backend graph available (e.g. run still in progress) — rebuild from events
        graphNodes = [];
        graphEdges = [];
        const addNode = (node: Node) => {
          if (!graphNodes.some((n) => n.id === node.id)) graphNodes.push(node);
        };
        const addEdge = (edge: Edge) => {
          if (!graphEdges.some((e) => e.id === edge.id)) graphEdges.push(edge);
        };
        const lastManagerId = () => {
          for (let i = graphNodes.length - 1; i >= 0; i--) {
            const nt = (graphNodes[i].data as Record<string, unknown>).nodeType ?? graphNodes[i].type;
            if (nt === 'manager' || nt === 'iteration') return graphNodes[i].id;
          }
          return null;
        };

        for (const evt of allEvents) {
          const d = evt.data;
          switch (evt.type) {
            case 'run.start': {
              const model = (d.model as string) ?? ((d.models as Record<string, string>)?.manager) ?? lastRun.model;
              addNode({ id: 'task_root', type: 'default', position: { x: 0, y: 0 }, data: { label: lastRun.task.slice(0, 60) || 'Task', status: 'running', nodeType: 'task', details: { model } } });
              addNode({ id: 'manager', type: 'default', position: { x: 0, y: 120 }, data: { label: `Manager (${model.split('/').pop()})`, status: 'running', nodeType: 'manager', details: d } });
              addEdge({ id: 'e-task-manager', source: 'task_root', target: 'manager' });
              break;
            }
            case 'delegation.start': {
              const parentId = (d.parent_id as string) ?? lastManagerId() ?? 'manager';
              const evtDepth = (d.depth as number) ?? 1;
              const model = (d.model as string) ?? '?';
              const subMgrId = `sub_mgr_${parentId}_d${evtDepth}`;
              addNode({ id: subMgrId, type: 'default', position: { x: 0, y: graphNodes.length * 120 }, data: { label: `Sub-Manager d${evtDepth} (${model.split('/').pop()})`, status: 'running', nodeType: 'manager', depth: evtDepth, details: d } });
              addEdge({ id: `e-${parentId}-${subMgrId}`, source: parentId, target: subMgrId });
              break;
            }
            case 'iteration.start': {
              const iterId = `iter_${d.iteration ?? '?'}`;
              const evtDepth = (d.depth as number) ?? 0;
              const parentWorkerId = d.parent_id as string | undefined;
              let iterParent = 'manager';
              if (parentWorkerId && evtDepth > 0) {
                const subMgrId = `sub_mgr_${parentWorkerId}_d${evtDepth}`;
                if (graphNodes.some((n) => n.id === subMgrId)) iterParent = subMgrId;
                else iterParent = parentWorkerId;
              }
              addNode({ id: iterId, type: 'default', position: { x: 0, y: graphNodes.length * 120 }, data: { label: `Iteration ${d.iteration ?? '?'}`, status: 'running', nodeType: 'iteration', depth: evtDepth, details: d } });
              addEdge({ id: `e-${iterParent}-${iterId}`, source: iterParent, target: iterId });
              break;
            }
            case 'iteration.decision': {
              const iterId = `iter_${d.iteration ?? '?'}`;
              const existing = graphNodes.find((n) => n.id === iterId);
              if (existing) {
                existing.data = { ...existing.data, status: (d.decision as string) === 'complete' ? 'complete' : 'running', label: `Iter ${d.iteration}: ${(d.decision as string ?? '').toUpperCase()}`, confidence: d.confidence, details: d };
              }
              break;
            }
            case 'worker.spawn': {
              const workerId = (d.worker_id as string) ?? nodeIdFromEvent(evt);
              const iteration = (d.iteration as string) ?? '';
              const workerNodeId = iteration ? `${workerId}_${iteration}` : workerId;
              const iterNodeId = iteration ? `iter_${iteration}` : null;
              const iterExists = iterNodeId && graphNodes.some((n) => n.id === iterNodeId);
              const parentId = (d.parent_id as string) ?? (iterExists ? iterNodeId! : lastManagerId() ?? 'manager');
              addNode({ id: workerNodeId, type: 'default', position: { x: 250, y: graphNodes.length * 120 }, data: { label: ((d.instructions as string) ?? '').slice(0, 60) || `Worker ${workerId.slice(0, 8)}`, status: 'running', nodeType: 'worker', details: d } });
              addEdge({ id: `e-${parentId}-${workerNodeId}`, source: parentId, target: workerNodeId });
              break;
            }
            case 'worker.complete': {
              const workerId = (d.worker_id as string) ?? nodeIdFromEvent(evt);
              const iteration = (d.iteration as string) ?? '';
              const workerNodeId = iteration ? `${workerId}_${iteration}` : workerId;
              const existing = graphNodes.find((n) => n.id === workerNodeId) ?? graphNodes.find((n) => n.id === workerId);
              if (existing) {
                existing.data = { ...existing.data, status: (d.error || d.has_error) ? 'error' : 'complete', confidence: d.confidence as number | undefined };
              }
              break;
            }
            case 'tool.call': {
              const toolName = (d.tool_name as string) ?? (d.tool as string) ?? 'Tool';
              const callerId = (d.worker_id as string) ?? (d.agent_id as string) ?? (d.caller_id as string) ?? '';
              const callIndex = d.call_index as number | undefined;
              const iteration = (d.iteration as string) ?? '';
              const uniqueSuffix = callIndex != null ? String(callIndex) : `t${graphNodes.length}`;
              const iterPrefix = iteration ? `${iteration}_` : '';
              const toolId = `tool-${iterPrefix}${callerId}-${toolName}-${uniqueSuffix}`;
              const callerNodeId = iteration ? `${callerId}_${iteration}` : callerId;
              const resolvedCallerId = graphNodes.some((n) => n.id === callerNodeId) ? callerNodeId : callerId;
              addNode({ id: toolId, type: 'default', position: { x: 450, y: graphNodes.length * 120 }, data: { label: toolName, status: (d.ok === false) ? 'error' : 'complete', nodeType: 'toolCall', details: d } });
              if (resolvedCallerId) addEdge({ id: `e-${resolvedCallerId}-${toolId}`, source: resolvedCallerId, target: toolId });
              break;
            }
            case 'run.complete': {
              const status = (d.status as string) ?? 'complete';
              const isError = status === 'error' || status === 'failed';
              const mgr = graphNodes.find((n) => n.id === 'manager');
              if (mgr) mgr.data = { ...mgr.data, status: isError ? 'error' : 'complete' };
              const root = graphNodes.find((n) => n.id === 'task_root');
              if (root) root.data = { ...root.data, status: isError ? 'error' : 'complete' };
              break;
            }
          }
        }
      }

      // Build session history for sidebar
      const sessionHistory: SessionHistoryItem[] = full.runs.flatMap((run) => [
        {
          role: 'user' as const,
          content: run.task,
          run_id: run.run_id,
          timestamp: run.created_at,
        },
        {
          role: 'assistant' as const,
          content: run.result
            ? JSON.stringify((run.result as Record<string, unknown>).result ?? run.result)
            : '',
          run_id: run.run_id,
          timestamp: run.completed_at ?? run.created_at,
          status: run.status,
        },
      ]);

      // If this session has a running run, reconnect WebSocket
      let wsConn: WebSocketConnection | null = null;
      let wsStatus: 'connecting' | 'open' | 'closed' | 'error' = 'closed';
      if (lastRunId && runStatus === 'running') {
        const pooledWs = s._wsPool.get(lastRunId);
        if (pooledWs) {
          wsConn = pooledWs;
          wsStatus = pooledWs.readyState() === WebSocket.OPEN ? 'open' : 'connecting';
        } else {
          // Reconnect WS for a running experiment (e.g. after page refresh)
          const conn = connectToRun(lastRunId, (event) => {
            const current = get();
            if (current.currentSessionId === sessionId) {
              current.addEvent(event);
            } else {
              routeBackgroundEvent(event, sessionId, get, set);
            }
            if (event.type === 'run.complete' || event.type === 'error') {
              api.listSessions().then((sessions) => set({ sessions })).catch(() => {});
            }
          }, {
            onStateChange: (ws) => {
              if (get().currentSessionId === sessionId) set({ _wsStatus: ws });
            },
          });
          s._wsPool.set(lastRunId, conn);
          s._runToSession.set(lastRunId, sessionId);
          wsConn = conn;
          wsStatus = 'connecting';
        }
      }

      set((prev) => ({
        currentSessionId: sessionId,
        currentRunId: lastRunId,
        runStatus,
        sessionHistory,
        outputBlocks,
        events: allEvents,
        graphNodes,
        graphEdges,
        selectedNodeId: null,
        activePanel: lastRun ? 'protocol' : 'protocol',
        config: { ...prev.config, ...configUpdate },
        budget: { ...DEFAULT_BUDGET },
        experimentMemory: full.memory ?? [],
        _wsConnection: wsConn,
        _wsStatus: wsStatus,
      }));

      // Fallback: if graph is still empty for a completed run, try loading from backend
      if (graphNodes.length === 0 && lastRunId && runStatus !== 'running') {
        get().loadRunGraph(lastRunId);
      }
    } catch (err) {
      // If full load fails, try basic load
      try {
        await api.getSession(sessionId);
        set({
          currentSessionId: sessionId,
          sessionHistory: [],
          outputBlocks: [],
          events: [],
          graphNodes: [],
          graphEdges: [],
          currentRunId: null,
          runStatus: 'idle',
          experimentMemory: [],
          _wsConnection: null,
          _wsStatus: 'closed',
        });
      } catch {
        set({ currentSessionId: sessionId, sessionHistory: [], experimentMemory: [] });
      }
    }
  },

  deleteSession: async (sessionId) => {
    try {
      await api.deleteSession(sessionId);
      const state = get();

      // Clean up cache
      state._sessionCache.delete(sessionId);

      // Close and remove any WS connections for this session's runs
      for (const [runId, sid] of state._runToSession.entries()) {
        if (sid === sessionId) {
          const ws = state._wsPool.get(runId);
          if (ws) {
            ws.close();
            state._wsPool.delete(runId);
          }
          state._runToSession.delete(runId);
        }
      }

      set((s) => {
        const sessions = s.sessions.filter((sess) => sess.id !== sessionId);
        const isCurrentDeleted = s.currentSessionId === sessionId;
        return {
          sessions,
          ...(isCurrentDeleted
            ? {
                currentSessionId: null,
                sessionHistory: [],
                outputBlocks: [],
                events: [],
                graphNodes: [],
                graphEdges: [],
                _wsConnection: null,
                _wsStatus: 'closed' as const,
              }
            : {}),
        };
      });
    } catch {
      // silently ignore
    }
  },

  renameSession: async (sessionId, title) => {
    try {
      await api.updateSession(sessionId, { title });
      set((s) => ({
        sessions: s.sessions.map((sess) =>
          sess.id === sessionId ? { ...sess, title } : sess,
        ),
      }));
    } catch {
      // silently ignore
    }
  },

  updateSessionMetadata: async (sessionId, update) => {
    try {
      await api.updateSession(sessionId, update);
      set((s) => ({
        sessions: s.sessions.map((sess) =>
          sess.id === sessionId ? { ...sess, ...update } : sess,
        ),
      }));
    } catch {
      // silently ignore
    }
  },

  // -- Experiment Memory -----------------------------------------------------
  experimentMemory: [],

  loadExperimentMemory: async () => {
    const sessionId = get().currentSessionId;
    if (!sessionId) {
      set({ experimentMemory: [] });
      return;
    }
    try {
      const memory = await api.getExperimentMemory(sessionId);
      set({ experimentMemory: memory });
    } catch {
      set({ experimentMemory: [] });
    }
  },

  addMemoryEntry: async (type, content, source = 'user') => {
    const sessionId = get().currentSessionId;
    if (!sessionId) return;
    try {
      const entry = await api.addMemoryEntry(sessionId, { type, content, source });
      set((s) => ({ experimentMemory: [entry, ...s.experimentMemory] }));
    } catch {
      // silently ignore
    }
  },

  updateMemoryEntry: async (memoryId, content) => {
    const sessionId = get().currentSessionId;
    if (!sessionId) return;
    try {
      await api.updateMemoryEntry(sessionId, memoryId, content);
      set((s) => ({
        experimentMemory: s.experimentMemory.map((m) =>
          m.id === memoryId ? { ...m, content, updated_at: new Date().toISOString() } : m,
        ),
      }));
    } catch {
      // silently ignore
    }
  },

  deleteMemoryEntry: async (memoryId) => {
    const sessionId = get().currentSessionId;
    if (!sessionId) return;
    try {
      await api.deleteMemoryEntry(sessionId, memoryId);
      set((s) => ({
        experimentMemory: s.experimentMemory.filter((m) => m.id !== memoryId),
      }));
    } catch {
      // silently ignore
    }
  },

  // -- Secrets --------------------------------------------------------------
  secrets: [],

  loadSecrets: async () => {
    try {
      const secrets = await api.listSecrets();
      set({ secrets });
    } catch {
      // silently ignore
    }
  },

  addSecret: async (key, value) => {
    try {
      await api.createSecret(key, value);
      const secrets = await api.listSecrets();
      set({ secrets });
    } catch {
      // silently ignore
    }
  },

  removeSecret: async (key) => {
    try {
      await api.deleteSecret(key);
      set((s) => ({
        secrets: s.secrets.filter((sec) => sec.key !== key),
      }));
    } catch {
      // silently ignore
    }
  },

  // -- Persistent settings --------------------------------------------------
  settingsLoaded: false,

  loadPersistedSettings: async () => {
    try {
      const saved = await api.loadSettings();
      if (saved) {
        // Extract UI state fields
        const {
          sidebar_open,
          inspector_open,
          active_panel,
          last_session_id,
          ...workflowSettings
        } = saved as Record<string, unknown>;

        const stateUpdate: Record<string, unknown> = {
          settingsLoaded: true,
        };

        // Apply workflow config settings
        if (Object.keys(workflowSettings).length > 0) {
          const s = get();
          stateUpdate.config = { ...s.config, ...workflowSettings };
        }

        // Apply UI state
        if (typeof sidebar_open === 'boolean') stateUpdate.sidebarOpen = sidebar_open;
        if (typeof inspector_open === 'boolean') stateUpdate.inspectorOpen = inspector_open;
        if (typeof active_panel === 'string') stateUpdate.activePanel = active_panel;
        if (typeof last_session_id === 'string' && last_session_id) {
          // Do NOT set currentSessionId here — let selectSession handle it
          // so the guard (currentSessionId === sessionId) won't block the full restore.
          get().selectSession(last_session_id).catch(() => {});
        }

        set(stateUpdate as Partial<WorkflowStore>);
      } else {
        set({ settingsLoaded: true });
      }
    } catch {
      set({ settingsLoaded: true });
    }
  },

  // -- Task Refactoring -----------------------------------------------------
  isRefactoring: false,
  refactorTask: async () => {
    const state = get();
    const task = state.config.task?.trim();
    if (!task || state.isRefactoring) return;
    set({ isRefactoring: true });
    try {
      const result = await api.refactorTask(task, state.config.model, state.config.api_key);
      set((s) => ({ config: { ...s.config, task: result.refactored_task } }));
    } catch (err) {
      const store = get() as ReturnType<typeof useWorkflowStore.getState>;
      store.addOutputBlock({
        type: 'error',
        content: `Task refactoring failed: ${err instanceof Error ? err.message : String(err)}`,
        title: 'Refactor Error',
      });
    } finally {
      set({ isRefactoring: false });
    }
  },

  saveCurrentSettings: async () => {
    try {
      const state = get();
      const { task: _task, output_dir: _outDir, input_files: _files, ...workflowSettings } = state.config;
      await api.saveSettings({
        ...workflowSettings,
        // UI state
        sidebar_open: state.sidebarOpen,
        inspector_open: state.inspectorOpen,
        active_panel: state.activePanel,
        last_session_id: state.currentSessionId,
      });
    } catch {
      // silently ignore
    }
  },

  // -- Internal WebSocket ---------------------------------------------------
  _wsConnection: null,
  _wsStatus: 'closed',

  // -- Session cache -------------------------------------------------------
  _sessionCache: new Map(),
  _wsPool: new Map(),
  _runToSession: new Map(),
}));
