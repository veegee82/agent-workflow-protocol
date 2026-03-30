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
import { connectToRun } from '@/api/websocket';

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
  max_tool_calls: 100,
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
  tool_calls_max: 100,
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

  // WebSocket handle (internal)
  _wsConnection: WebSocketConnection | null;
  _wsStatus: 'connecting' | 'open' | 'closed' | 'error';
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
  const store = get();

  switch (evt.type) {
    case 'agent.start':
    case 'delegation.start': {
      const id = nodeIdFromEvent(evt);
      const node: Node = {
        id,
        type: 'default',
        position: { x: 0, y: store.graphNodes.length * 120 },
        data: {
          label: (evt.data.agent_name as string) ?? evt.type,
          status: 'running',
          details: evt.data,
          nodeType: evt.type === 'delegation.start' ? 'manager' : 'task',
        },
      };
      store.addGraphNode(node);
      break;
    }

    case 'worker.spawn': {
      const workerId = nodeIdFromEvent(evt);
      const parentId = (evt.data.parent_id as string) ?? '';
      const node: Node = {
        id: workerId,
        type: 'default',
        position: {
          x: 200,
          y: store.graphNodes.length * 120,
        },
        data: {
          label: (evt.data.task as string) ?? 'Worker',
          status: 'running',
          details: evt.data,
          nodeType: 'worker',
        },
      };
      store.addGraphNode(node);
      if (parentId) {
        store.addGraphEdge({
          id: `e-${parentId}-${workerId}`,
          source: parentId,
          target: workerId,
          animated: true,
        });
      }
      break;
    }

    case 'agent.complete':
    case 'worker.complete': {
      const id = nodeIdFromEvent(evt);
      store.updateGraphNode(id, {
        status: 'complete',
        confidence: evt.data.confidence as number | undefined,
        outputs: evt.data.result as Record<string, unknown> | undefined,
      });

      // Add output block for completed agents
      if (evt.data.result) {
        store.addOutputBlock({
          type: 'json',
          content: JSON.stringify(evt.data.result, null, 2),
          title: (evt.data.agent_name as string) ?? 'Result',
        });
      }
      break;
    }

    case 'tool.call': {
      const toolId = nodeIdFromEvent(evt);
      const callerId =
        (evt.data.agent_id as string) ?? (evt.data.caller_id as string) ?? '';
      const node: Node = {
        id: toolId,
        type: 'default',
        position: { x: 400, y: store.graphNodes.length * 120 },
        data: {
          label: (evt.data.tool_name as string) ?? 'Tool',
          status: 'running',
          details: evt.data,
          nodeType: 'toolCall',
        },
      };
      store.addGraphNode(node);
      if (callerId) {
        store.addGraphEdge({
          id: `e-${callerId}-${toolId}`,
          source: callerId,
          target: toolId,
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

    case 'iteration.start': {
      store.addOutputBlock({
        type: 'markdown',
        content: `**Iteration ${evt.data.iteration ?? '?'}**`,
        title: 'Iteration',
      });
      break;
    }

    case 'iteration.decision': {
      store.addOutputBlock({
        type: 'markdown',
        content:
          (evt.data.reasoning as string) ??
          JSON.stringify(evt.data, null, 2),
        title: 'Decision',
      });
      break;
    }

    case 'budget.update': {
      store.updateBudget(evt.data as Partial<BudgetState>);
      break;
    }

    case 'run.complete': {
      set({
        runStatus: 'complete',
      });
      if (evt.data.result) {
        store.addOutputBlock({
          type: 'markdown',
          content:
            typeof evt.data.result === 'string'
              ? (evt.data.result as string)
              : JSON.stringify(evt.data.result, null, 2),
          title: 'Final Result',
        });
      }
      break;
    }

    case 'run.error': {
      set({ runStatus: 'error' });
      store.addOutputBlock({
        type: 'error',
        content: (evt.data.error as string) ?? 'Unknown error',
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

  // -- Output ---------------------------------------------------------------
  outputBlocks: [],
  addOutputBlock: (block) =>
    set((s) => ({ outputBlocks: [...s.outputBlocks, block] })),

  // -- Budget ---------------------------------------------------------------
  budget: { ...DEFAULT_BUDGET },
  updateBudget: (partial) =>
    set((s) => ({ budget: { ...s.budget, ...partial } })),

  // -- UI state -------------------------------------------------------------
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
      budget: {
        ...DEFAULT_BUDGET,
        loops_max: state.config.max_loops,
        tokens_max: state.config.max_total_tokens,
        workers_max: state.config.max_total_workers,
        wall_time_max_ms: state.config.max_wall_time * 1000,
        tool_calls_max: state.config.max_tool_calls,
      },
      selectedNodeId: null,
      activePanel: 'output',
    });

    try {
      // Upload attached files if any
      if (state.attachedFiles.length > 0) {
        await api.uploadFiles(state.attachedFiles);
      }

      // Start the run on the backend
      const { run_id } = await api.startRun(state.config);
      set({ currentRunId: run_id });

      // Open WebSocket
      const conn = connectToRun(run_id, (event) => get().addEvent(event), {
        onStateChange: (ws) => set({ _wsStatus: ws }),
      });
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

  // -- Internal WebSocket ---------------------------------------------------
  _wsConnection: null,
  _wsStatus: 'closed',
}));
