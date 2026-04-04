import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
import {
  Diamond,
  Star,
  RefreshCw,
  Circle,
  Wrench,
  CheckSquare,
  Maximize,
  Activity,
  Users,
  GitBranch,
  Zap,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useWorkflowStore } from '@/stores/workflowStore';
import { customNodeTypes } from './CustomNodes';

// ---------------------------------------------------------------------------
// Enhanced layout with better spacing and grouping
// ---------------------------------------------------------------------------

function layoutNodes(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  // Build adjacency
  const childrenMap = new Map<string, string[]>();
  const parentMap = new Map<string, string>();
  const nodeMap = new Map<string, Node>();
  for (const n of nodes) {
    childrenMap.set(n.id, []);
    nodeMap.set(n.id, n);
  }
  for (const e of edges) {
    const ch = childrenMap.get(e.source);
    if (ch && nodeMap.has(e.target)) {
      ch.push(e.target);
      parentMap.set(e.target, e.source);
    }
  }

  const nt = (id: string) => nodeMap.get(id)?.data?.nodeType ?? nodeMap.get(id)?.type ?? '';

  // Layout constants
  const COL_GAP = 220;   // horizontal gap between columns (workers, tools)
  const ROW_GAP = 160;   // vertical gap between iteration rows
  const TOOL_Y_OFFSET = 120; // tool calls sit below their worker within the same row band

  const positions = new Map<string, { x: number; y: number }>();

  // Find roots
  const roots = nodes.filter((n) => !parentMap.has(n.id)).map((n) => n.id);
  if (roots.length === 0 && nodes.length > 0) roots.push(nodes[0].id);

  // -----------------------------------------------------------------------
  // Row-based layout: iterations are rows, workers/tools are columns
  //
  // Structure:  root → manager → iter0 → [worker0, worker1, ...]
  //                             iter1 → [worker2, ...]
  //                             ...
  //
  // Row 0: root (task)
  // Row 1: manager
  // Row 2: iter000  |  worker_a  worker_b  (+ tool calls below each worker)
  // Row 3: iter001  |  worker_c
  // ...
  // Last:  completion
  // -----------------------------------------------------------------------

  // Collect iterations ordered under each manager, and workers under each iteration
  // For each iteration, compute how many "sub-rows" it needs (1 if no tools, 2 if tools)
  /**
   * Lay out a manager node and all its iterations/workers/tools/sub-managers.
   * Returns the next available row after the subtree.
   */
  function layoutManager(mgrId: string, startRow: number, xCenter: number): number {
    let row = startRow;
    positions.set(mgrId, { x: xCenter, y: row * ROW_GAP });
    row++;

    const iterChildren = (childrenMap.get(mgrId) ?? []).filter((c) => nodeMap.has(c));
    const iterIds = iterChildren.filter((c) => nt(c) === 'iteration');
    const mgrOther = iterChildren.filter((c) => nt(c) !== 'iteration');

    for (const iterId of iterIds) {
      const iterKids = (childrenMap.get(iterId) ?? []).filter((c) => nodeMap.has(c));
      const workerIds = iterKids.filter((c) => nt(c) === 'worker');
      const otherIterKids = iterKids.filter((c) => nt(c) !== 'worker');

      const iterY = row * ROW_GAP;
      positions.set(iterId, { x: xCenter, y: iterY });

      let col = 1;
      let hasToolRow = false;
      let maxSubRow = row + 1;
      for (const wId of workerIds) {
        const wx = xCenter + col * COL_GAP;
        positions.set(wId, { x: wx, y: iterY });

        const wKids = (childrenMap.get(wId) ?? []).filter((c) => nodeMap.has(c));
        const toolIds = wKids.filter((c) => nt(c) === 'toolCall');
        const subMgrIds = wKids.filter((c) => nt(c) === 'manager');
        const otherKids = wKids.filter((c) => nt(c) !== 'toolCall' && nt(c) !== 'manager');

        if (toolIds.length > 0) {
          hasToolRow = true;
          const toolSpacing = Math.min(COL_GAP * 0.55, COL_GAP / Math.max(1, toolIds.length));
          for (let ti = 0; ti < toolIds.length; ti++) {
            positions.set(toolIds[ti], {
              x: wx + ti * toolSpacing,
              y: iterY + TOOL_Y_OFFSET,
            });
          }
          const toolSpread = (toolIds.length - 1) * toolSpacing;
          col += Math.max(1, Math.ceil((toolSpread + COL_GAP * 0.3) / COL_GAP));
        } else {
          col++;
        }

        // Sub-managers (A4 recursive delegation) — layout recursively below
        if (subMgrIds.length > 0) {
          let subRow = row + (hasToolRow ? 2 : 1);
          for (const subMgrId of subMgrIds) {
            subRow = layoutManager(subMgrId, subRow, wx);
          }
          maxSubRow = Math.max(maxSubRow, subRow);
        }

        // Other non-tool, non-manager children
        for (const otherId of otherKids) {
          if (!positions.has(otherId)) {
            const subRow = row + (hasToolRow ? 2 : 1);
            maxSubRow = Math.max(maxSubRow, collectSubtree(otherId, subRow, wx));
          }
        }
      }

      for (const otherId of otherIterKids) {
        positions.set(otherId, { x: xCenter + col * COL_GAP, y: iterY });
        col++;
      }

      row = Math.max(row + (hasToolRow ? 2 : 1), maxSubRow);
    }

    // Non-iteration children of manager (e.g. completion)
    for (const otherId of mgrOther) {
      if (!positions.has(otherId)) {
        positions.set(otherId, { x: xCenter, y: row * ROW_GAP });
        row++;
      }
    }

    return row;
  }

  function collectSubtree(rootId: string, startRow: number, xCenter: number): number {
    const type = nt(rootId);
    let row = startRow;

    // If root is a manager (e.g. sub-manager), layout it and its subtree
    if (type === 'manager') {
      return layoutManager(rootId, startRow, xCenter);
    }

    // Place root (task node)
    if (type === 'task' || type === 'completion' || (!type && !parentMap.has(rootId))) {
      positions.set(rootId, { x: xCenter, y: row * ROW_GAP });
      row++;
    }

    const rootChildren = (childrenMap.get(rootId) ?? []).filter((c) => nodeMap.has(c));

    // Find manager children
    const managerIds = rootChildren.filter((c) => nt(c) === 'manager');
    const otherChildren = rootChildren.filter((c) => nt(c) !== 'manager');

    for (const mgrId of managerIds) {
      row = layoutManager(mgrId, row, xCenter);
    }

    // Non-manager children of root (e.g. completion node)
    for (const otherId of otherChildren) {
      if (!positions.has(otherId)) {
        positions.set(otherId, { x: xCenter, y: row * ROW_GAP });
        row++;
      }
    }

    return row;
  }

  let currentRow = 0;
  for (const rootId of roots) {
    currentRow = collectSubtree(rootId, currentRow, 0);
  }

  // Place any unpositioned nodes (safety net)
  for (const n of nodes) {
    if (!positions.has(n.id)) {
      positions.set(n.id, { x: 0, y: currentRow * ROW_GAP });
      currentRow++;
    }
  }

  return nodes.map((n) => ({
    ...n,
    position: positions.get(n.id) ?? n.position,
  }));
}

// ---------------------------------------------------------------------------
// Edge styling with color based on source node type
// ---------------------------------------------------------------------------

function getEdgeColor(sourceNode: Node | undefined): string {
  const nodeType = sourceNode?.data?.nodeType ?? sourceNode?.type;
  switch (nodeType) {
    case 'task': return '#40C4FF';
    case 'manager': return '#E040FB';
    case 'iteration': return '#FFD600';
    case 'worker': return '#18FFFF';
    case 'toolCall': return '#00E676';
    case 'completion': return '#00E676';
    default: return '#30363d';
  }
}

function styledEdges(edges: Edge[], nodes: Node[]): Edge[] {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  return edges.map((edge) => {
    const sourceNode = nodeMap.get(edge.source);
    const color = getEdgeColor(sourceNode);
    const isAnimated = edge.animated;
    return {
      ...edge,
      type: 'smoothstep',
      animated: isAnimated,
      style: {
        stroke: color,
        strokeWidth: isAnimated ? 2.5 : 1.5,
        opacity: isAnimated ? 1 : 0.6,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color,
        width: 16,
        height: 16,
      },
    };
  });
}

// ---------------------------------------------------------------------------
// Stats bar
// ---------------------------------------------------------------------------

interface GraphStats {
  total: number;
  tasks: number;
  managers: number;
  subManagers: number;
  iterations: number;
  workers: number;
  toolCalls: number;
  completions: number;
  running: number;
  complete: number;
  errors: number;
}

function computeStats(nodes: Node[]): GraphStats {
  const stats: GraphStats = {
    total: nodes.length, tasks: 0, managers: 0, subManagers: 0, iterations: 0,
    workers: 0, toolCalls: 0, completions: 0, running: 0, complete: 0, errors: 0,
  };
  for (const n of nodes) {
    const nt = n.data?.nodeType ?? n.type;
    const st = n.data?.status;
    const depth = n.data?.depth as number | undefined;
    if (nt === 'task') stats.tasks++;
    else if (nt === 'manager' && depth && depth > 0) stats.subManagers++;
    else if (nt === 'manager') stats.managers++;
    else if (nt === 'iteration') stats.iterations++;
    else if (nt === 'worker') stats.workers++;
    else if (nt === 'toolCall') stats.toolCalls++;
    else if (nt === 'completion') stats.completions++;
    if (st === 'running') stats.running++;
    else if (st === 'complete') stats.complete++;
    else if (st === 'error') stats.errors++;
  }
  return stats;
}

function StatsBar({ stats }: { stats: GraphStats }) {
  return (
    <div className="absolute top-4 left-4 z-10 flex items-center gap-1 rounded-xl bg-awp-panel/90 backdrop-blur-md border border-awp-border/60 px-3 py-2 shadow-xl">
      <StatPill icon={<Activity className="h-3 w-3" />} value={stats.total} label="nodes" color="text-awp-text" />
      <Separator />
      <StatPill icon={<RefreshCw className="h-3 w-3" />} value={stats.iterations} label="iter" color="text-awp-yellow" />
      <StatPill icon={<Users className="h-3 w-3" />} value={stats.workers} label="workers" color="text-awp-cyan" />
      {stats.subManagers > 0 && (
        <StatPill icon={<GitBranch className="h-3 w-3" />} value={stats.subManagers} label="sub-mgr" color="text-awp-purple" />
      )}
      <StatPill icon={<Wrench className="h-3 w-3" />} value={stats.toolCalls} label="tools" color="text-awp-green" />
      <Separator />
      {stats.running > 0 && (
        <StatPill icon={<Zap className="h-3 w-3" />} value={stats.running} label="running" color="text-awp-blue" pulse />
      )}
      {stats.errors > 0 && (
        <StatPill icon={<X className="h-3 w-3" />} value={stats.errors} label="errors" color="text-awp-red" />
      )}
    </div>
  );
}

function StatPill({ icon, value, label, color, pulse }: {
  icon: React.ReactNode; value: number; label: string; color: string; pulse?: boolean;
}) {
  return (
    <div className={clsx('flex items-center gap-1.5 px-2 py-0.5 rounded-lg', pulse && 'animate-pulse')}>
      <span className={color}>{icon}</span>
      <span className={clsx('text-xs font-bold tabular-nums', color)}>{value}</span>
      <span className="text-[10px] text-awp-muted">{label}</span>
    </div>
  );
}

function Separator() {
  return <div className="w-px h-4 bg-awp-border/60 mx-1" />;
}

// ---------------------------------------------------------------------------
// Filter toolbar
// ---------------------------------------------------------------------------

interface FilterState {
  showTools: boolean;
  showWorkers: boolean;
  showIterations: boolean;
}

function FilterToolbar({
  filters,
  setFilters,
  onFitView,
  autoFit,
  onToggleAutoFit,
}: {
  filters: FilterState;
  setFilters: React.Dispatch<React.SetStateAction<FilterState>>;
  onFitView: () => void;
  autoFit: boolean;
  onToggleAutoFit: () => void;
}) {
  return (
    <div className="absolute top-4 right-4 z-10 flex flex-col gap-2">
      {/* Zoom controls */}
      <div className="flex flex-col rounded-xl bg-awp-panel/90 backdrop-blur-md border border-awp-border/60 shadow-xl overflow-hidden">
        <ToolbarButton
          tooltip="Fit to view"
          onClick={onFitView}
          icon={<Maximize className="h-4 w-4" />}
        />
        <ToolbarToggle
          tooltip="Auto-fit on new nodes"
          active={autoFit}
          onClick={onToggleAutoFit}
          icon={<GitBranch className="h-3.5 w-3.5" />}
          color="text-awp-blue"
        />
      </div>

      {/* Filters */}
      <div className="flex flex-col rounded-xl bg-awp-panel/90 backdrop-blur-md border border-awp-border/60 shadow-xl overflow-hidden">
        <ToolbarToggle
          tooltip="Tools"
          active={filters.showTools}
          onClick={() => setFilters((f) => ({ ...f, showTools: !f.showTools }))}
          icon={<Wrench className="h-3.5 w-3.5" />}
          color="text-awp-green"
        />
        <ToolbarToggle
          tooltip="Workers"
          active={filters.showWorkers}
          onClick={() => setFilters((f) => ({ ...f, showWorkers: !f.showWorkers }))}
          icon={<Circle className="h-3.5 w-3.5" />}
          color="text-awp-cyan"
        />
        <ToolbarToggle
          tooltip="Iterations"
          active={filters.showIterations}
          onClick={() => setFilters((f) => ({ ...f, showIterations: !f.showIterations }))}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          color="text-awp-yellow"
        />
      </div>
    </div>
  );
}

function ToolbarButton({ tooltip, onClick, icon }: {
  tooltip: string; onClick: () => void; icon: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={tooltip}
      className="flex items-center justify-center w-9 h-9 text-awp-muted hover:text-awp-text hover:bg-awp-border/40 transition-all duration-150"
    >
      {icon}
    </button>
  );
}

function ToolbarToggle({ tooltip, active, onClick, icon, color }: {
  tooltip: string; active: boolean; onClick: () => void; icon: React.ReactNode; color: string;
}) {
  return (
    <button
      onClick={onClick}
      title={tooltip}
      className={clsx(
        'flex items-center justify-center w-9 h-9 transition-all duration-150',
        active
          ? `${color} bg-awp-border/20 hover:bg-awp-border/40`
          : 'text-awp-muted/40 hover:text-awp-muted hover:bg-awp-border/20',
      )}
    >
      {icon}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Floating legend
// ---------------------------------------------------------------------------

function Legend() {
  const [open, setOpen] = useState(false);

  const items = [
    { icon: <Diamond className="h-3 w-3 text-awp-blue" />, label: 'Task', color: 'bg-awp-blue' },
    { icon: <Star className="h-3 w-3 text-awp-purple fill-awp-purple/30" />, label: 'Manager', color: 'bg-awp-purple' },
    { icon: <GitBranch className="h-3 w-3 text-awp-purple" />, label: 'Sub-Manager', color: 'bg-awp-purple' },
    { icon: <RefreshCw className="h-3 w-3 text-awp-yellow" />, label: 'Iteration', color: 'bg-awp-yellow' },
    { icon: <Circle className="h-3 w-3 text-awp-cyan" />, label: 'Worker', color: 'bg-awp-cyan' },
    { icon: <Wrench className="h-3 w-3 text-awp-green" />, label: 'Tool Call', color: 'bg-awp-green' },
    { icon: <CheckSquare className="h-3 w-3 text-awp-green" />, label: 'Completion', color: 'bg-awp-green' },
  ];

  const statuses = [
    { label: 'Running', color: 'bg-awp-blue', pulse: true },
    { label: 'Complete', color: 'bg-awp-green', pulse: false },
    { label: 'Error', color: 'bg-awp-red', pulse: false },
    { label: 'Pending', color: 'bg-awp-muted', pulse: false },
  ];

  return (
    <div className="absolute bottom-4 left-4 z-10">
      {open ? (
        <div className="rounded-xl bg-awp-panel/90 backdrop-blur-md border border-awp-border/60 shadow-xl p-3 w-52 animate-fade-in">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold text-awp-text uppercase tracking-wider">Legend</span>
            <button onClick={() => setOpen(false)} className="text-awp-muted hover:text-awp-text transition-colors">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="space-y-1">
            <div className="text-[9px] text-awp-muted uppercase tracking-wider mb-1">Node Types</div>
            {items.map((item) => (
              <div key={item.label} className="flex items-center gap-2 py-0.5">
                {item.icon}
                <span className="text-[11px] text-awp-text">{item.label}</span>
              </div>
            ))}
          </div>

          <div className="mt-2 pt-2 border-t border-awp-border/40 space-y-1">
            <div className="text-[9px] text-awp-muted uppercase tracking-wider mb-1">Status</div>
            {statuses.map((s) => (
              <div key={s.label} className="flex items-center gap-2 py-0.5">
                <span className="relative flex h-2.5 w-2.5">
                  {s.pulse && (
                    <span className={clsx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-75', s.color)} />
                  )}
                  <span className={clsx('relative inline-flex h-2.5 w-2.5 rounded-full', s.color)} />
                </span>
                <span className="text-[11px] text-awp-text">{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="rounded-xl bg-awp-panel/90 backdrop-blur-md border border-awp-border/60 shadow-xl px-3 py-2 flex items-center gap-2 text-awp-muted hover:text-awp-text transition-colors"
        >
          <div className="flex -space-x-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-awp-blue border border-awp-panel" />
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-awp-purple border border-awp-panel" />
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-awp-yellow border border-awp-panel" />
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-awp-green border border-awp-panel" />
          </div>
          <span className="text-[11px]">Legend</span>
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Node detail tooltip (shown on hover)
// ---------------------------------------------------------------------------

function TooltipRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-1">
      <span className="text-[10px] text-awp-muted shrink-0 w-[72px] text-right uppercase tracking-wider pt-px">{label}</span>
      <span className="text-[11px] text-awp-text flex-1 min-w-0">{children}</span>
    </div>
  );
}

function NodeTooltip({ node, position }: { node: Node; position: { x: number; y: number } }) {
  const d = node.data ?? {};
  const nodeType = (d.nodeType ?? node.type ?? 'unknown') as string;
  const status = (d.status ?? 'pending') as string;
  const confidence = d.confidence as number | undefined;
  const label = (d.label ?? node.id) as string;
  const error = d.error as string | undefined;
  const tools = d.tools_used as string[] | undefined;
  const toolCount = d.toolCount as number | undefined;
  const model = d.model as string | undefined;
  const decision = d.decision as string | undefined;
  const iteration = d.iteration;
  const reasoning = d.reasoning as string | undefined;
  const instructions = d.instructions as string | undefined;
  const toolsAllowed = d.toolsAllowed as string[] | undefined;
  const toolsCreated = d.tools_created as string[] | undefined;
  const budget = d.budget as Record<string, unknown> | undefined;
  const finalBudget = d.finalBudget as Record<string, unknown> | undefined;
  const task = d.task as string | undefined;
  const runId = d.run_id as string | undefined;
  const models = d.models as Record<string, string> | undefined;
  const stdout = d.stdout as string | undefined;
  const stderr = d.stderr as string | undefined;
  const toolArgs = d.arguments as Record<string, unknown> | undefined;
  const toolOutput = d.output as string | undefined;
  const timing = d.timing as { start?: string; end?: string; duration_ms?: number } | undefined;
  const iterationCount = d.iterationCount ?? d.totalIterations;
  const codeMode = d.code_mode;
  const skills = d.skills as string[] | undefined;
  const outputs = d.outputs as Record<string, unknown> | undefined;
  const workerId = d.worker_id as string | undefined;

  const typeIcons: Record<string, { icon: React.ReactNode; color: string; border: string }> = {
    task: { icon: <Diamond className="h-3.5 w-3.5" />, color: 'text-awp-blue', border: 'border-awp-blue/50' },
    manager: { icon: <Star className="h-3.5 w-3.5 fill-current/30" />, color: 'text-awp-purple', border: 'border-awp-purple/50' },
    iteration: { icon: <RefreshCw className="h-3.5 w-3.5" />, color: 'text-awp-yellow', border: 'border-awp-yellow/50' },
    worker: { icon: <Circle className="h-3.5 w-3.5" />, color: 'text-awp-cyan', border: 'border-awp-cyan/50' },
    toolCall: { icon: <Wrench className="h-3.5 w-3.5" />, color: 'text-awp-green', border: 'border-awp-green/50' },
    completion: { icon: <CheckSquare className="h-3.5 w-3.5" />, color: 'text-awp-green', border: 'border-awp-green/50' },
  };
  const typeInfo = typeIcons[nodeType] ?? { icon: null, color: 'text-awp-muted', border: 'border-awp-border/60' };

  // Clamp tooltip so it doesn't overflow the viewport
  const left = Math.min(position.x + 16, window.innerWidth - 380);
  const top = Math.min(position.y - 12, window.innerHeight - 400);

  return (
    <div
      className={clsx(
        'fixed z-50 pointer-events-none animate-fade-in',
        'rounded-xl bg-awp-panel/95 backdrop-blur-md border shadow-2xl',
        'min-w-[260px] max-w-[360px] overflow-hidden',
        typeInfo.border,
      )}
      style={{ left, top }}
    >
      {/* Header */}
      <div className={clsx('flex items-center gap-2 px-4 py-2.5 border-b border-awp-border/30', `bg-gradient-to-r from-awp-bg/80 to-transparent`)}>
        <span className={typeInfo.color}>{typeInfo.icon}</span>
        <span className="text-xs font-semibold text-awp-text truncate flex-1">{label}</span>
        <StatusBadge status={status} />
      </div>

      {/* Body */}
      <div className="px-4 py-2.5 space-y-0.5 divide-y divide-awp-border/20">
        {/* Type & ID */}
        <div className="pb-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-awp-muted uppercase tracking-wider">{nodeType}</span>
            {workerId && <span className="text-[9px] text-awp-muted/60 font-mono">{workerId}</span>}
            {runId && <span className="text-[9px] text-awp-muted/60 font-mono">{runId}</span>}
          </div>
        </div>

        {/* Task (for task nodes) */}
        {task && (
          <div className="pt-1.5">
            <TooltipRow label="Task">
              <span className="line-clamp-3">{task}</span>
            </TooltipRow>
          </div>
        )}

        {/* Model */}
        {(model || models) && (
          <div className="pt-1.5">
            {model && <TooltipRow label="Model"><span className="font-mono text-[10px]">{model}</span></TooltipRow>}
            {models && !model && Object.entries(models).map(([k, v]) => (
              <TooltipRow key={k} label={k}><span className="font-mono text-[10px]">{v}</span></TooltipRow>
            ))}
          </div>
        )}

        {/* Iteration / Decision */}
        {(iteration !== undefined || decision) && (
          <div className="pt-1.5">
            {iteration !== undefined && <TooltipRow label="Iteration"><span className="font-mono font-bold">{String(iteration)}</span></TooltipRow>}
            {decision && (
              <TooltipRow label="Decision">
                <span className={clsx(
                  'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold',
                  decision === 'delegate' ? 'bg-awp-yellow/15 text-awp-yellow' :
                  decision === 'complete' ? 'bg-awp-green/15 text-awp-green' :
                  'bg-awp-red/15 text-awp-red',
                )}>{decision.toUpperCase()}</span>
              </TooltipRow>
            )}
          </div>
        )}

        {/* Confidence */}
        {confidence !== undefined && (
          <div className="pt-1.5">
            <div className="flex items-center gap-2 py-1">
              <span className="text-[10px] text-awp-muted shrink-0 w-[72px] text-right uppercase tracking-wider">Confidence</span>
              <ConfidenceBar value={confidence} />
              <span className={clsx(
                'text-[11px] font-mono font-bold tabular-nums',
                confidence >= 0.8 ? 'text-awp-green' : confidence >= 0.5 ? 'text-awp-yellow' : 'text-awp-red',
              )}>
                {(confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        )}

        {/* Instructions (workers) */}
        {instructions && (
          <div className="pt-1.5">
            <TooltipRow label="Task">
              <span className="line-clamp-3 text-[10px]">{instructions}</span>
            </TooltipRow>
          </div>
        )}

        {/* Reasoning (iterations) */}
        {reasoning && (
          <div className="pt-1.5">
            <TooltipRow label="Reasoning">
              <span className="line-clamp-3 text-[10px] italic text-awp-muted">{reasoning}</span>
            </TooltipRow>
          </div>
        )}

        {/* Tools */}
        {(tools && tools.length > 0) && (
          <div className="pt-1.5">
            <TooltipRow label="Tools">
              <div className="flex flex-wrap gap-1">
                {tools.slice(0, 8).map((t, i) => (
                  <span key={i} className="inline-flex items-center gap-0.5 rounded-md bg-awp-bg/80 px-1.5 py-0.5 text-[9px] text-awp-green font-mono">
                    <Wrench className="h-2 w-2" />{t}
                  </span>
                ))}
                {tools.length > 8 && <span className="text-[9px] text-awp-muted">+{tools.length - 8}</span>}
              </div>
            </TooltipRow>
          </div>
        )}

        {/* Tools allowed (workers) */}
        {toolsAllowed && toolsAllowed.length > 0 && !tools && (
          <div className="pt-1.5">
            <TooltipRow label="Tools">
              <div className="flex flex-wrap gap-1">
                {toolsAllowed.slice(0, 6).map((t, i) => (
                  <span key={i} className="rounded-md bg-awp-bg/80 px-1.5 py-0.5 text-[9px] text-awp-muted font-mono">{t}</span>
                ))}
                {toolsAllowed.length > 6 && <span className="text-[9px] text-awp-muted">+{toolsAllowed.length - 6}</span>}
              </div>
            </TooltipRow>
          </div>
        )}

        {/* Tools created */}
        {toolsCreated && toolsCreated.length > 0 && (
          <div className="pt-1.5">
            <TooltipRow label="Created">
              <div className="flex flex-wrap gap-1">
                {toolsCreated.map((t, i) => (
                  <span key={i} className="rounded-md bg-awp-purple/10 border border-awp-purple/20 px-1.5 py-0.5 text-[9px] text-awp-purple font-mono">{t}</span>
                ))}
              </div>
            </TooltipRow>
          </div>
        )}

        {toolCount !== undefined && !tools && !toolsAllowed && (
          <div className="pt-1.5">
            <TooltipRow label="Tools">{toolCount} tool call{toolCount !== 1 ? 's' : ''}</TooltipRow>
          </div>
        )}

        {/* Tool call details */}
        {toolArgs && (
          <div className="pt-1.5">
            <TooltipRow label="Args">
              <div className="rounded overflow-hidden line-clamp-4">
                <SyntaxHighlighter
                  language="json"
                  style={oneDark}
                  customStyle={{ margin: 0, padding: '0.375rem 0.5rem', background: 'rgba(13,17,23,0.6)', fontSize: '0.5625rem', lineHeight: '1.4' }}
                  wrapLines
                  wrapLongLines
                >
                  {JSON.stringify(toolArgs, null, 2)}
                </SyntaxHighlighter>
              </div>
            </TooltipRow>
          </div>
        )}
        {(stdout || toolOutput) && (
          <div className="pt-1.5">
            <TooltipRow label="Output">
              <div className="rounded overflow-hidden line-clamp-4">
                <SyntaxHighlighter
                  language="text"
                  style={oneDark}
                  customStyle={{ margin: 0, padding: '0.375rem 0.5rem', background: 'rgba(13,17,23,0.6)', fontSize: '0.5625rem', lineHeight: '1.4' }}
                  wrapLines
                  wrapLongLines
                >
                  {String(stdout || toolOutput)}
                </SyntaxHighlighter>
              </div>
            </TooltipRow>
          </div>
        )}
        {stderr && (
          <div className="pt-1.5">
            <TooltipRow label="Stderr">
              <div className="rounded overflow-hidden line-clamp-3">
                <SyntaxHighlighter
                  language="text"
                  style={oneDark}
                  customStyle={{ margin: 0, padding: '0.375rem 0.5rem', background: 'rgba(13,17,23,0.6)', fontSize: '0.5625rem', lineHeight: '1.4' }}
                  wrapLines
                  wrapLongLines
                >
                  {stderr}
                </SyntaxHighlighter>
              </div>
            </TooltipRow>
          </div>
        )}

        {/* Skills / Code mode */}
        {(skills && skills.length > 0 || codeMode !== undefined) && (
          <div className="pt-1.5 flex items-center gap-2">
            {codeMode !== undefined && (
              <span className={clsx('rounded-md px-1.5 py-0.5 text-[9px] font-medium', codeMode ? 'bg-awp-blue/10 text-awp-blue' : 'bg-awp-muted/10 text-awp-muted')}>
                Code: {codeMode ? 'ON' : 'OFF'}
              </span>
            )}
            {skills && skills.map((s, i) => (
              <span key={i} className="rounded-md bg-awp-purple/10 px-1.5 py-0.5 text-[9px] text-awp-purple">{s}</span>
            ))}
          </div>
        )}

        {/* Budget */}
        {(budget || finalBudget) && (
          <div className="pt-1.5">
            <TooltipRow label="Budget">
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[9px] font-mono">
                {Object.entries(finalBudget ?? budget ?? {}).slice(0, 8).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-1">
                    <span className="text-awp-muted truncate">{k.replace(/_/g, ' ')}</span>
                    <span className="text-awp-text font-semibold">{String(v)}</span>
                  </div>
                ))}
              </div>
            </TooltipRow>
          </div>
        )}

        {/* Timing */}
        {timing && timing.duration_ms !== undefined && (
          <div className="pt-1.5">
            <TooltipRow label="Duration">
              <span className="font-mono text-[10px]">{(timing.duration_ms / 1000).toFixed(1)}s</span>
            </TooltipRow>
          </div>
        )}

        {/* Iteration count (completion nodes) */}
        {iterationCount !== undefined && (
          <div className="pt-1.5">
            <TooltipRow label="Iterations"><span className="font-mono font-bold">{String(iterationCount)}</span></TooltipRow>
          </div>
        )}

        {/* Outputs (agent.complete) */}
        {outputs && Object.keys(outputs).length > 0 && (
          <div className="pt-1.5">
            <TooltipRow label="Output">
              <div className="rounded overflow-hidden line-clamp-4">
                <SyntaxHighlighter
                  language="json"
                  style={oneDark}
                  customStyle={{ margin: 0, padding: '0.375rem 0.5rem', background: 'rgba(13,17,23,0.6)', fontSize: '0.5625rem', lineHeight: '1.4' }}
                  wrapLines
                  wrapLongLines
                >
                  {JSON.stringify(outputs, null, 2)}
                </SyntaxHighlighter>
              </div>
            </TooltipRow>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="pt-1.5">
            <div className="rounded-md bg-awp-red/10 border border-awp-red/20 px-2.5 py-1.5">
              <div className="text-[9px] text-awp-red/70 uppercase tracking-wider mb-0.5">Error</div>
              <span className="text-[10px] text-awp-red line-clamp-4">{error}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: 'bg-awp-blue/15 text-awp-blue border-awp-blue/30',
    complete: 'bg-awp-green/15 text-awp-green border-awp-green/30',
    error: 'bg-awp-red/15 text-awp-red border-awp-red/30',
    pending: 'bg-awp-muted/15 text-awp-muted border-awp-muted/30',
  };
  return (
    <span className={clsx(
      'inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-medium',
      colors[status] ?? colors.pending,
    )}>
      {status === 'running' && <span className="mr-1 h-1.5 w-1.5 rounded-full bg-current animate-pulse" />}
      {status}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 0.8 ? 'bg-awp-green' : value >= 0.5 ? 'bg-awp-yellow' : 'bg-awp-red';
  return (
    <div className="flex-1 h-1.5 rounded-full bg-awp-border/40 overflow-hidden min-w-[40px]">
      <div
        className={clsx('h-full rounded-full transition-all duration-500', color)}
        style={{ width: `${value * 100}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-awp-muted">
      <div className="relative">
        <div className="absolute inset-0 rounded-full bg-awp-blue/5 blur-3xl scale-150" />
        <div className="relative rounded-2xl border-2 border-dashed border-awp-border/40 p-8">
          <GitBranch className="h-16 w-16 text-awp-border/60" />
        </div>
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-awp-text/60">No execution graph yet</p>
        <p className="text-xs text-awp-muted mt-1">Start a workflow to see the interactive visualization</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main GraphVisPanel
// ---------------------------------------------------------------------------

export function GraphVisPanel() {
  const storeNodes = useWorkflowStore((s) => s.graphNodes);
  const storeEdges = useWorkflowStore((s) => s.graphEdges);
  const selectNode = useWorkflowStore((s) => s.selectNode);
  const currentRunId = useWorkflowStore((s) => s.currentRunId);
  const runStatus = useWorkflowStore((s) => s.runStatus);
  const loadRunGraph = useWorkflowStore((s) => s.loadRunGraph);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [hoveredNode, setHoveredNode] = useState<Node | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [filters, setFilters] = useState<FilterState>({
    showTools: true,
    showWorkers: true,
    showIterations: true,
  });
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);
  const [autoFit, setAutoFit] = useState(true);
  const prevNodeCountRef = useRef(0);

  // Load graph from backend if needed
  useEffect(() => {
    if (currentRunId && storeNodes.length === 0 && runStatus !== 'running') {
      loadRunGraph(currentRunId);
    }
  }, [currentRunId, storeNodes.length, runStatus, loadRunGraph]);

  // Filter nodes based on visibility toggles
  const filteredData = useMemo(() => {
    const hiddenTypes = new Set<string>();
    if (!filters.showTools) hiddenTypes.add('toolCall');
    if (!filters.showWorkers) hiddenTypes.add('worker');
    if (!filters.showIterations) hiddenTypes.add('iteration');

    const visibleNodes = storeNodes.filter((n) => {
      const nt = n.data?.nodeType ?? n.type;
      return !hiddenTypes.has(nt);
    });
    const visibleIds = new Set(visibleNodes.map((n) => n.id));
    const visibleEdges = storeEdges.filter(
      (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
    );

    return { nodes: visibleNodes, edges: visibleEdges };
  }, [storeNodes, storeEdges, filters]);

  // Layout and style — auto-fit when new nodes arrive
  useEffect(() => {
    const mapped = filteredData.nodes.map((n) => ({
      ...n,
      type: n.data?.nodeType ?? 'task',
    }));
    const laid = layoutNodes(mapped, filteredData.edges);
    setNodes(laid);
    setEdges(styledEdges(filteredData.edges, laid));

    // Auto-fit view when node count changes (new nodes added)
    const nodeCount = filteredData.nodes.length;
    if (autoFit && reactFlowInstance && nodeCount > 0 && nodeCount !== prevNodeCountRef.current) {
      // Small delay to let ReactFlow render the new nodes before fitting
      setTimeout(() => {
        reactFlowInstance.fitView({ padding: 0.3, duration: 300 });
      }, 50);
    }
    prevNodeCountRef.current = nodeCount;
  }, [filteredData, setNodes, setEdges, autoFit, reactFlowInstance]);

  const stats = useMemo(() => computeStats(storeNodes), [storeNodes]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      selectNode(node.id);
    },
    [selectNode],
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const onNodeMouseEnter = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setHoveredNode(node);
    },
    [],
  );

  const onNodeMouseLeave = useCallback(() => {
    setHoveredNode(null);
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    setMousePos({ x: e.clientX, y: e.clientY });
  }, []);

  const handleFitView = useCallback(() => {
    reactFlowInstance?.fitView({ padding: 0.3, duration: 400 });
  }, [reactFlowInstance]);

  const nodeTypes = useMemo(() => customNodeTypes, []);

  if (storeNodes.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="h-full w-full relative" onMouseMove={handleMouseMove}>
      {/* Stats overlay */}
      <StatsBar stats={stats} />

      {/* Filter controls */}
      <FilterToolbar
        filters={filters}
        setFilters={setFilters}
        onFitView={handleFitView}
        autoFit={autoFit}
        onToggleAutoFit={() => setAutoFit((v) => !v)}
      />

      {/* Legend */}
      <Legend />

      {/* ReactFlow canvas */}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
        onInit={setReactFlowInstance}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.1}
        maxZoom={3}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          type: 'smoothstep',
        }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color="#1c2128"
          gap={24}
          size={1.5}
        />
        <Controls
          className="!bg-awp-panel/90 !backdrop-blur-md !border-awp-border/60 !rounded-xl !shadow-xl [&>button]:!bg-transparent [&>button]:!border-awp-border/30 [&>button]:!text-awp-muted [&>button:hover]:!bg-awp-border/40 [&>button:hover]:!text-awp-text [&>button]:!rounded-lg [&>button]:!transition-all [&>button]:!duration-150"
          showInteractive={false}
          position="bottom-right"
        />
        <MiniMap
          className="!bg-awp-panel/90 !backdrop-blur-md !border-awp-border/60 !rounded-xl !shadow-xl"
          nodeColor={(n) => {
            const nt = n.data?.nodeType ?? n.type;
            const st = n.data?.status;
            if (st === 'error') return '#FF1744';
            if (st === 'running') return '#40C4FF';
            switch (nt) {
              case 'task': return '#40C4FF';
              case 'manager': return '#E040FB';
              case 'iteration': return '#FFD600';
              case 'worker': return '#18FFFF';
              case 'toolCall': return '#00E676';
              case 'completion': return '#00E676';
              default: return '#8b949e';
            }
          }}
          maskColor="rgba(13, 17, 23, 0.85)"
          pannable
          zoomable
        />
      </ReactFlow>

      {/* Hover tooltip */}
      {hoveredNode && (
        <NodeTooltip node={hoveredNode} position={mousePos} />
      )}
    </div>
  );
}
