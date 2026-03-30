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
} from '@/types';
import * as api from '@/api/client';
import { connectToRun, type ConnectionState } from '@/api/websocket';

// ---------------------------------------------------------------------------
// Default values
// ---------------------------------------------------------------------------

const DEFAULT_CONFIG: WorkflowConfig = {
  task: '',
  model: 'anthropic/claude-sonnet-4-20250514',
  worker_model: undefined,
  api_key: undefined,
  max_loops: 20,
  max_total_tokens: 2_000_000,
  max_wall_time: 600,
  max_tool_calls: 200,
  max_total_workers: 10,
  max_depth: 3,
  sandbox: 'subprocess',
  packages: [],
  code_mode: true,
  tool_creation: false,
  tools: [],
  forbidden_tools: [],
  verbose: false,
};

const DEFAULT_BUDGET: BudgetState = {
  loops_used: 0,
  loops_max: 20,
  tokens_used: 0,
  tokens_max: 2_000_000,
  workers_used: 0,
  workers_max: 10,
  wall_time_ms: 0,
  wall_time_max_ms: 600_000,
  tool_calls_used: 0,
  tool_calls_max: 200,
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

  // WebSocket
  wsConnection: WebSocketConnection | null;
  wsState: ConnectionState;

  // Graph
  graphNodes: Node[];
  graphEdges: Edge[];
  addGraphNode: (node: Node) => void;
  addGraphEdge: (edge: Edge) => void;
  selectedNodeId: string | null;
  selectNode: (id: string | null) => void;

  // Output
  outputBlocks: OutputBlock[];
  addOutputBlock: (block: OutputBlock) => void;

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
}

// ---------------------------------------------------------------------------
// Helpers for translating events into graph / output / budget updates
// ---------------------------------------------------------------------------

function nodeColor(status: string): string {
  switch (status) {
    case 'running':
      return '#40C4FF';
    case 'complete':
      return '#00E676';
    case 'error':
      return '#FF1744';
    default:
      return '#8b949e';
  }
}

function buildNode(
  id: string,
  label: string,
  type: string,
  status: string,
  extra: Record<string, unknown> = {},
  position?: { x: number; y: number },
): Node {
  return {
    id,
    type: 'default',
    position: position ?? { x: 0, y: 0 },
    data: {
      label,
      nodeType: type,
      status,
      ...extra,
    },
    style: {
      background: '#161b22',
      color: '#c9d1d9',
      border: `2px solid ${nodeColor(status)}`,
      borderRadius: 12,
      padding: 12,
      fontSize: 13,
      minWidth: 160,
    },
  };
}

/** Auto-layout: simple grid placement based on current node count. */
function autoPosition(existingCount: number): { x: number; y: number } {
  const cols = 3;
  const xGap = 280;
  const yGap = 140;
  const col = existingCount % cols;
  const row = Math.floor(existingCount / cols);
  return { x: col * xGap + 40, y: row * yGap + 40 };
}

// ---------------------------------------------------------------------------
// Store implementation
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
  addEvent: (event) => set((s) => ({ events: [...s.events, event] })),

  // -- WebSocket ------------------------------------------------------------
  wsConnection: null,
  wsState: 'closed',

  // -- Graph ----------------------------------------------------------------
  graphNodes: [],
  graphEdges: [],
  addGraphNode: (node) =>
    set((s) => ({ graphNodes: [...s.graphNodes, node] })),
  addGraphEdge: (edge) =>
    set((s) => ({ graphEdges: [...s.graphEdges, edge] })),
  selectedNodeId: null,
  selectNode: (id) => set({ selectedNodeId: id, inspectorOpen: id !== null }),

  // -- Output ---------------------------------------------------------------
  outputBlocks: [],
  addOutputBlock: (block) =>
    set((s) => ({ outputBlocks: [...s.outputBlocks, block] })),

  // -- Budget ---------------------------------------------------------------
  budget: { ...DEFAULT_BUDGET },
  updateBudget: (partial) =>
    set((s) => ({ budget: { ...s.budget, ...partial } })),

  // -- UI -------------------------------------------------------------------
  activePanel: 'output',
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
      const history = await api.listRuns();
      set({ runHistory: history });
    } catch {
      // Silently ignore -- the server may not be up yet
    }
  },

  // -- Files ----------------------------------------------------------------
  attachedFiles: [],
  addFiles: (files) =>
    set((s) => ({ attachedFiles: [...s.attachedFiles, ...files] })),
  removeFile: (index) =>
    set((s) => ({
      attachedFiles: s.attachedFiles.filter((_, i) => i !== index),
    })),

  // -- Actions --------------------------------------------------------------
  startRun: async () => {
    const state = get();
    if (state.runStatus === 'running') return;

    // Reset transient state
    set({
      events: [],
      graphNodes: [],
      graphEdges: [],
      outputBlocks: [],
      budget: {
        ...DEFAULT_BUDGET,
        loops_max: state.config.max_loops,
        tokens_max: state.config.max_total_tokens,
        workers_max: state.config.max_total_workers,
        wall_time_max_ms: state.config.max_wall_time * 1000,
        tool_calls_max: state.config.max_tool_calls,
      },
      selectedNodeId: null,
      inspectorOpen: false,
      activePanel: 'output',
      runStatus: 'running',
    });

    try {
      // Upload attached files first
      if (state.attachedFiles.length > 0) {
        await api.uploadFiles(state.attachedFiles);
      }

      const { run_id } = await api.startRun(state.config);
      set({ currentRunId: run_id });

      // Connect WebSocket
      const conn = connectToRun(
        run_id,
        (event) => {
          const s = get();
          s.addEvent(event);
          handleEvent(event, get, set);
        },
        {
          onStateChange: (wsState) => set({ wsState }),
          onFatalError: () =>
            set({ runStatus: 'error', wsState: 'closed' }),
        },
      );

      set({ wsConnection: conn });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      set({ runStatus: 'error' });
      get().addOutputBlock({ type: 'error', content: message });
    }
  },

  stopRun: async () => {
    const { currentRunId, wsConnection } = get();
    if (currentRunId) {
      try {
        await api.stopRun(currentRunId);
      } catch {
        // best-effort
      }
    }
    wsConnection?.close();
    set({ runStatus: 'complete', wsConnection: null, wsState: 'closed' });
  },

  reset: () => {
    const { wsConnection } = get();
    wsConnection?.close();
    set({
      currentRunId: null,
      runStatus: 'idle',
      events: [],
      graphNodes: [],
      graphEdges: [],
      outputBlocks: [],
      budget: { ...DEFAULT_BUDGET },
      selectedNodeId: null,
      inspectorOpen: false,
      wsConnection: null,
      wsState: 'closed',
      attachedFiles: [],
    });
  },
}));

// ---------------------------------------------------------------------------
// Event handler -- translates RunEvents into store mutations
// ---------------------------------------------------------------------------

type SetFn = (
  partial:
    | Partial<WorkflowStore>
    | ((state: WorkflowStore) => Partial<WorkflowStore>),
) => void;
type GetFn = () => WorkflowStore;

function handleEvent(event: RunEvent, get: GetFn, set: SetFn) {
  const { data } = event;

  switch (event.type) {
    case 'agent.start': {
      const id = (data.agent_id as string) ?? `agent-${Date.now()}`;
      const label = (data.name as string) ?? id;
      const nodeType = (data.role as string) === 'manager' ? 'manager' : 'task';
      const pos = autoPosition(get().graphNodes.length);
      const node = buildNode(id, label, nodeType, 'running', {
        timing: { start: event.timestamp },
      }, pos);
      get().addGraphNode(node);
      break;
    }

    case 'agent.complete': {
      const id = (data.agent_id as string) ?? '';
      set((s) => ({
        graphNodes: s.graphNodes.map((n) =>
          n.id === id
            ? {
                ...n,
                data: {
                  ...n.data,
                  status: 'complete',
                  confidence: data.confidence as number | undefined,
                  outputs: data.result as Record<string, unknown> | undefined,
                  timing: {
                    ...(n.data.timing as Record<string, unknown>),
                    end: event.timestamp,
                    duration_ms: data.duration_ms as number | undefined,
                  },
                },
                style: {
                  ...n.style,
                  border: `2px solid ${nodeColor('complete')}`,
                },
              }
            : n,
        ),
      }));

      // Add result as output block
      if (data.result) {
        get().addOutputBlock({
          type: 'markdown',
          content:
            typeof data.result === 'string'
              ? data.result
              : JSON.stringify(data.result, null, 2),
          title: `Agent: ${data.name ?? id}`,
        });
      }
      break;
    }

    case 'tool.call': {
      const toolId = `tool-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const label = (data.tool as string) ?? 'tool';
      const pos = autoPosition(get().graphNodes.length);
      const node = buildNode(toolId, label, 'toolCall', 'running', {
        inputs: data.arguments as Record<string, unknown> | undefined,
      }, pos);
      get().addGraphNode(node);

      // Connect to parent agent if available
      const parentId = data.agent_id as string | undefined;
      if (parentId) {
        get().addGraphEdge({
          id: `e-${parentId}-${toolId}`,
          source: parentId,
          target: toolId,
          animated: true,
          style: { stroke: '#40C4FF', strokeWidth: 2 },
        });
      }
      break;
    }

    case 'tool.result': {
      // Find the most recent running toolCall node
      set((s) => {
        const idx = [...s.graphNodes]
          .reverse()
          .findIndex(
            (n) =>
              n.data.nodeType === 'toolCall' && n.data.status === 'running',
          );
        if (idx === -1) return {};
        const realIdx = s.graphNodes.length - 1 - idx;
        const updated = [...s.graphNodes];
        updated[realIdx] = {
          ...updated[realIdx],
          data: {
            ...updated[realIdx].data,
            status: 'complete',
            outputs: data as Record<string, unknown>,
          },
          style: {
            ...updated[realIdx].style,
            border: `2px solid ${nodeColor('complete')}`,
          },
        };
        return { graphNodes: updated };
      });
      break;
    }

    case 'iteration.start': {
      const iterId = `iter-${data.loop ?? Date.now()}`;
      const pos = autoPosition(get().graphNodes.length);
      const node = buildNode(
        iterId,
        `Iteration ${data.loop ?? '?'}`,
        'iteration',
        'running',
        {},
        pos,
      );
      get().addGraphNode(node);
      break;
    }

    case 'iteration.decision': {
      get().addOutputBlock({
        type: 'markdown',
        content: `**Decision (loop ${data.loop ?? '?'}):** ${data.decision ?? 'unknown'}`,
      });
      break;
    }

    case 'budget.update': {
      get().updateBudget(data as Partial<BudgetState>);
      break;
    }

    case 'worker.spawn': {
      const workerId =
        (data.worker_id as string) ?? `worker-${Date.now()}`;
      const label = (data.task as string) ?? workerId;
      const pos = autoPosition(get().graphNodes.length);
      const node = buildNode(workerId, label, 'worker', 'running', {}, pos);
      get().addGraphNode(node);

      const managerId = data.manager_id as string | undefined;
      if (managerId) {
        get().addGraphEdge({
          id: `e-${managerId}-${workerId}`,
          source: managerId,
          target: workerId,
          animated: true,
          style: { stroke: '#E040FB', strokeWidth: 2 },
        });
      }
      break;
    }

    case 'worker.complete': {
      const wId = (data.worker_id as string) ?? '';
      set((s) => ({
        graphNodes: s.graphNodes.map((n) =>
          n.id === wId
            ? {
                ...n,
                data: {
                  ...n.data,
                  status: data.error ? 'error' : 'complete',
                  outputs: data.result as Record<string, unknown> | undefined,
                  error: data.error as string | undefined,
                },
                style: {
                  ...n.style,
                  border: `2px solid ${nodeColor(data.error ? 'error' : 'complete')}`,
                },
              }
            : n,
        ),
      }));
      break;
    }

    case 'delegation.start': {
      get().addOutputBlock({
        type: 'markdown',
        content: `**Delegation started** -- manager dispatching workers`,
        title: 'Delegation',
      });
      break;
    }

    case 'run.complete': {
      set({ runStatus: 'complete' });
      if (data.result) {
        get().addOutputBlock({
          type: 'markdown',
          content:
            typeof data.result === 'string'
              ? data.result
              : JSON.stringify(data.result, null, 2),
          title: 'Final Result',
        });
      }
      get().wsConnection?.close();
      set({ wsConnection: null, wsState: 'closed' });
      break;
    }

    case 'run.error': {
      set({ runStatus: 'error' });
      get().addOutputBlock({
        type: 'error',
        content: (data.error as string) ?? 'Unknown error',
        title: 'Run Error',
      });
      get().wsConnection?.close();
      set({ wsConnection: null, wsState: 'closed' });
      break;
    }

    case 'log': {
      const level = (data.level as string) ?? 'info';
      const message = (data.message as string) ?? '';
      if (level === 'error') {
        get().addOutputBlock({ type: 'error', content: message });
      } else {
        get().addOutputBlock({ type: 'markdown', content: message });
      }
      break;
    }
  }
}
