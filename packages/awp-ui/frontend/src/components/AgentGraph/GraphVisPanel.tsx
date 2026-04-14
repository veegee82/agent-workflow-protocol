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

function layoutNodes(nodes: Node[], _edges: Edge[]): Node[] {
  // Backend graph_builder.py computes the authoritative column layout.
  // During live runs, the debounced loadRunGraph() replaces event-based
  // placeholder nodes with backend-positioned nodes every 800ms.
  return nodes;
}

// @ts-ignore — disabled legacy layout, kept for reference
function _layoutNodes_DISABLED(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  // -----------------------------------------------------------------------
  // 2-Pass block layout (DISABLED — using backend positions)
  //
  // PASS 1 (buildBlock): walk the tree bottom-up. For each manager node we
  //   compute a Block { iters, subs[], totalWidthPx, totalHeightPx } that
  //   describes the bounding box of the entire subtree (manager + iterations
  //   + workers + tools + nested sub-manager blocks).
  //
  // PASS 2 (placeBlock): walk the tree top-down. Each block is placed at an
  //   absolute (x, y). Sub-manager blocks are packed side-by-side to the
  //   RIGHT of their parent's own area, all starting at the parent manager's
  //   Y so the tree grows in width, not depth. Because each block knows its
  //   own totalWidthPx, sibling sub-blocks never overlap with each other or
  //   with the parent's content.
  //
  // Cycle protection via inProgress set.
  // -----------------------------------------------------------------------

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
  const isWorkerLike = (id: string) => nt(id) === 'worker' || nt(id) === 'submanager';

  // Layout constants (px)
  const COL_GAP = 240;
  const ROW_GAP = 170;
  const TOOL_Y_OFFSET = 110;
  const LANE_GAP = 100;     // horizontal gap between sibling sub-manager blocks
  const ROOT_GAP_Y = 200;   // vertical gap between independent root subtrees
  const SAFETY_X = -COL_GAP * 3;

  const positions = new Map<string, { x: number; y: number }>();

  type WorkerCell = { id: string; col: number; tools: string[] };
  type IterPlan = {
    id: string;
    rowIdx: number;        // row offset from block top (manager row = 0)
    rowSpan: number;       // 1 normally, 2 if iteration has tool calls
    workers: WorkerCell[];
    others: { id: string; col: number }[];
  };
  type Block = {
    mgrId: string;
    iters: IterPlan[];
    mgrOthers: string[];   // non-iteration children (e.g. completion nodes)
    selfCols: number;      // own area width in COL_GAP units (manager + workers)
    selfRows: number;      // own area height in ROW_GAP units
    subs: Block[];
    totalWidthPx: number;
    totalHeightPx: number;
  };

  const blockCache = new Map<string, Block>();
  const inProgress = new Set<string>();

  function emptyBlock(mgrId: string): Block {
    return {
      mgrId, iters: [], mgrOthers: [],
      selfCols: 1, selfRows: 1, subs: [],
      totalWidthPx: COL_GAP, totalHeightPx: ROW_GAP,
    };
  }

  function buildBlock(mgrId: string): Block {
    const cached = blockCache.get(mgrId);
    if (cached) return cached;
    if (inProgress.has(mgrId)) return emptyBlock(mgrId); // cycle guard
    inProgress.add(mgrId);

    const allKids = (childrenMap.get(mgrId) ?? []).filter((c) => nodeMap.has(c));
    const iterIds = allKids.filter((c) => nt(c) === 'iteration');
    const mgrOthers = allKids.filter((c) => nt(c) !== 'iteration');

    const iters: IterPlan[] = [];
    const subs: Block[] = [];
    let rowCursor = 1; // manager header occupies row 0
    let maxCols = 1;   // at least one col for the manager itself

    for (const iterId of iterIds) {
      const iterKids = (childrenMap.get(iterId) ?? []).filter((c) => nodeMap.has(c));
      const workerIds = iterKids.filter(isWorkerLike);
      const otherIds = iterKids.filter((c) => !isWorkerLike(c));

      const workers: WorkerCell[] = [];
      let col = 1;
      let hasToolRow = false;

      for (const wId of workerIds) {
        const wKids = (childrenMap.get(wId) ?? []).filter((c) => nodeMap.has(c));
        const tools = wKids.filter((c) => nt(c) === 'toolCall');
        const subMgrIds = wKids.filter((c) => nt(c) === 'manager');

        workers.push({ id: wId, col, tools });

        // Reserve column space for tool fan-out
        let workerColSpan = 1;
        if (tools.length > 0) {
          hasToolRow = true;
          const toolSpacing = Math.min(COL_GAP * 0.55, COL_GAP / Math.max(1, tools.length));
          const toolSpread = (tools.length - 1) * toolSpacing;
          workerColSpan = Math.max(1, Math.ceil((toolSpread + COL_GAP * 0.4) / COL_GAP));
        }
        col += workerColSpan;

        // Recursively build sub-manager blocks (bottom-up)
        for (const sub of subMgrIds) {
          if (!blockCache.has(sub)) subs.push(buildBlock(sub));
          else subs.push(blockCache.get(sub)!);
        }
      }

      // Reserve cols for "others" on the iteration row
      const others: { id: string; col: number }[] = [];
      for (const oid of otherIds) {
        others.push({ id: oid, col });
        col += 1;
      }

      const rowSpan = hasToolRow ? 2 : 1;
      iters.push({ id: iterId, rowIdx: rowCursor, rowSpan, workers, others });
      maxCols = Math.max(maxCols, col);
      rowCursor += rowSpan;
    }

    // Reserve rows for non-iteration children stacked under the manager column
    const mgrOtherRows = mgrOthers.length;
    const selfRows = Math.max(1, rowCursor + mgrOtherRows);
    const selfCols = Math.max(1, maxCols);

    const selfWidthPx = selfCols * COL_GAP;
    const selfHeightPx = selfRows * ROW_GAP;

    // Sub-blocks are placed side-by-side starting after the self area, all at
    // the same Y as the parent manager.
    const subsWidthPx = subs.reduce(
      (acc, b) => acc + b.totalWidthPx + LANE_GAP,
      0,
    );
    const subsMaxHeightPx = subs.length > 0
      ? Math.max(...subs.map((b) => b.totalHeightPx))
      : 0;

    const totalWidthPx = selfWidthPx + (subs.length > 0 ? LANE_GAP + subsWidthPx : 0);
    const totalHeightPx = Math.max(selfHeightPx, subsMaxHeightPx);

    const block: Block = {
      mgrId, iters, mgrOthers,
      selfCols, selfRows, subs,
      totalWidthPx, totalHeightPx,
    };
    blockCache.set(mgrId, block);
    inProgress.delete(mgrId);
    return block;
  }

  function placeBlock(block: Block, x: number, y: number): void {
    // Manager header
    positions.set(block.mgrId, { x, y });

    // Iterations + workers + tools
    for (const iter of block.iters) {
      const iterY = y + iter.rowIdx * ROW_GAP;
      positions.set(iter.id, { x, y: iterY });

      for (const w of iter.workers) {
        const wx = x + w.col * COL_GAP;
        positions.set(w.id, { x: wx, y: iterY });

        if (w.tools.length > 0) {
          const toolSpacing = Math.min(COL_GAP * 0.55, COL_GAP / Math.max(1, w.tools.length));
          for (let ti = 0; ti < w.tools.length; ti++) {
            positions.set(w.tools[ti], {
              x: wx + ti * toolSpacing,
              y: iterY + TOOL_Y_OFFSET,
            });
          }
        }
      }

      for (const o of iter.others) {
        positions.set(o.id, { x: x + o.col * COL_GAP, y: iterY });
      }
    }

    // Non-iteration children of the manager (completion etc.) stacked under
    // the iteration column.
    let stackRow = block.iters.length > 0
      ? block.iters[block.iters.length - 1].rowIdx + block.iters[block.iters.length - 1].rowSpan
      : 1;
    for (const otherId of block.mgrOthers) {
      if (!positions.has(otherId)) {
        positions.set(otherId, { x, y: y + stackRow * ROW_GAP });
        stackRow++;
      }
    }

    // Sub-manager blocks: side-by-side, all at parent manager's Y. The tree
    // grows in WIDTH, not depth. Each sub-block is fully self-contained so no
    // overlap with siblings or parent content is possible.
    let subX = x + block.selfCols * COL_GAP + LANE_GAP;
    for (const sub of block.subs) {
      placeBlock(sub, subX, y);
      subX += sub.totalWidthPx + LANE_GAP;
    }
  }

  // Find roots (nodes without parents in the edge graph)
  const roots = nodes.filter((n) => !parentMap.has(n.id)).map((n) => n.id);
  if (roots.length === 0 && nodes.length > 0) roots.push(nodes[0].id);

  // Walk roots. A root may be a task (whose first child is a manager) or a
  // bare manager. Each root subtree gets its own vertical band so independent
  // roots never overlap.
  let currentRootY = 0;

  function placeRootSubtree(rootId: string): void {
    const rootType = nt(rootId);

    if (rootType === 'manager') {
      const block = buildBlock(rootId);
      placeBlock(block, 0, currentRootY);
      currentRootY += block.totalHeightPx + ROOT_GAP_Y;
      return;
    }

    // Non-manager root: place it at the top of its band, then recurse into
    // its manager / non-manager children.
    let row = 0;
    if (!positions.has(rootId)) {
      positions.set(rootId, { x: 0, y: currentRootY });
      row++;
    }

    const kids = (childrenMap.get(rootId) ?? []).filter((c) => nodeMap.has(c));
    const mgrKids = kids.filter((c) => nt(c) === 'manager');
    const otherKids = kids.filter((c) => nt(c) !== 'manager');

    let bandHeightPx = row * ROW_GAP;
    for (const mgrId of mgrKids) {
      const block = buildBlock(mgrId);
      placeBlock(block, 0, currentRootY + bandHeightPx);
      bandHeightPx += block.totalHeightPx + ROW_GAP;
    }

    for (const otherId of otherKids) {
      if (!positions.has(otherId)) {
        positions.set(otherId, { x: 0, y: currentRootY + bandHeightPx });
        bandHeightPx += ROW_GAP;
      }
    }

    currentRootY += bandHeightPx + ROOT_GAP_Y;
  }

  for (const rootId of roots) {
    placeRootSubtree(rootId);
  }

  // Safety net for any unreachable / orphan nodes — push them off to the left
  // so they don't visually collide with the main layout.
  let safetyY = 0;
  for (const n of nodes) {
    if (!positions.has(n.id)) {
      positions.set(n.id, { x: SAFETY_X, y: safetyY });
      safetyY += ROW_GAP;
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
                    <span className="text-awp-text font-semibold">
                      {v != null && typeof v === 'object'
                        ? Object.entries(v as Record<string, unknown>).map(([sk, sv]) => `${sk}: ${sv}`).join(', ')
                        : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </TooltipRow>
          </div>
        )}

        {/* Eval Score */}
        {typeof d.eval_score === 'number' && (
          <div className="pt-1.5">
            <TooltipRow label="Eval Score">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className={clsx(
                    'font-mono font-bold text-[11px]',
                    d.eval_score as number >= 0.75 ? 'text-emerald-400'
                      : d.eval_score as number >= 0.5 ? 'text-yellow-400'
                        : 'text-red-400',
                  )}>
                    {(d.eval_score as number * 100).toFixed(0)}%
                  </span>
                  <span className="text-[9px] text-awp-muted">{String(d.eval_action ?? '')}</span>
                </div>
                {Array.isArray(d.eval_metrics) && (d.eval_metrics as Array<{name: string; score: number; weight: number}>).map((m: {name: string; score: number; weight: number}) => (
                  <div key={m.name} className="flex items-center gap-1 text-[9px]">
                    <span className="text-awp-muted w-16 truncate">{m.name}</span>
                    <div className="flex-1 h-1 rounded-full bg-awp-border overflow-hidden">
                      <div
                        className={clsx('h-full rounded-full',
                          m.score >= 0.65 ? 'bg-emerald-500' : m.score >= 0.4 ? 'bg-yellow-500' : 'bg-red-500'
                        )}
                        style={{ width: `${Math.round(m.score * 100)}%` }}
                      />
                    </div>
                    <span className="font-mono w-6 text-right">{(m.score * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </TooltipRow>
          </div>
        )}

        {/* Critique Score */}
        {typeof d.critique_score === 'number' && (
          <div className="pt-1.5">
            <TooltipRow label="Critique">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className={clsx(
                    'font-mono font-bold text-[11px]',
                    d.critique_score as number >= 0.8 ? 'text-emerald-400'
                      : d.critique_score as number >= 0.5 ? 'text-amber-400'
                        : 'text-rose-400',
                  )}>
                    {(d.critique_score as number * 100).toFixed(0)}%
                  </span>
                  {d.critique_summary && (
                    <span className="text-[9px] text-awp-muted">{String(d.critique_summary)}</span>
                  )}
                </div>
                {Array.isArray(d.critique_defects) && (d.critique_defects as Array<{category: string; severity: string; description: string}>).map((df: {category: string; severity: string; description: string}, idx: number) => (
                  <div key={idx} className="flex items-center gap-1 text-[9px]">
                    <span className={clsx(
                      'px-1 rounded text-[8px] font-bold',
                      df.severity === 'critical' ? 'bg-rose-500/20 text-rose-400'
                        : df.severity === 'warning' ? 'bg-amber-500/20 text-amber-400'
                          : 'bg-sky-500/20 text-sky-400',
                    )}>
                      {df.severity.toUpperCase()}
                    </span>
                    <span className="text-awp-muted">{df.category}:</span>
                    <span className="text-awp-text truncate max-w-[150px]">{df.description}</span>
                  </div>
                ))}
                {Array.isArray(d.critique_repairs) && (d.critique_repairs as Array<{attempt: number; original_score: number; repaired_score: number; defects_fixed: number}>).length > 0 && (
                  <div className="mt-1 border-t border-awp-border pt-1">
                    <span className="text-[9px] text-amber-400 font-medium">Repairs:</span>
                    {(d.critique_repairs as Array<{attempt: number; original_score: number; repaired_score: number; defects_fixed: number}>).map((r: {attempt: number; original_score: number; repaired_score: number; defects_fixed: number}) => (
                      <div key={r.attempt} className="text-[9px] text-awp-muted">
                        #{r.attempt}: {(r.original_score * 100).toFixed(0)}% → {(r.repaired_score * 100).toFixed(0)}% ({r.defects_fixed} fixed)
                      </div>
                    ))}
                  </div>
                )}
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

  // Structural fingerprint: only recompute layout when the set of node IDs
  // or edge IDs changes (i.e. nodes added/removed), not on data-only updates
  // like status or confidence changes. This eliminates O(n) layout + fitView
  // recalculations on every worker.complete or tool.call event.
  const structureKey = useMemo(
    () => filteredData.nodes.map((n) => n.id).join('|') + '::' + filteredData.edges.map((e) => e.id).join('|'),
    [filteredData],
  );
  const prevStructureRef = useRef(structureKey);
  const layoutCacheRef = useRef<{ nodes: Node[]; edges: Edge[] } | null>(null);

  // Track whether a fitView is pending (structure changed but instance wasn't ready)
  const pendingFitRef = useRef(false);

  // Full layout pass — only runs when structure changes
  useEffect(() => {
    const structureChanged = structureKey !== prevStructureRef.current;
    prevStructureRef.current = structureKey;

    if (structureChanged || !layoutCacheRef.current) {
      // Structure changed: recompute layout
      const mapped = filteredData.nodes.map((n) => ({
        ...n,
        type: n.data?.nodeType ?? 'task',
      }));
      const laid = layoutNodes(mapped, filteredData.edges);
      const styled = styledEdges(filteredData.edges, laid);
      layoutCacheRef.current = { nodes: laid, edges: styled };
      setNodes(laid);
      setEdges(styled);

      // Mark that we need a fitView for this structure change
      const nodeCount = filteredData.nodes.length;
      if (autoFit && nodeCount > 0) {
        pendingFitRef.current = true;
      }
      prevNodeCountRef.current = nodeCount;
    } else {
      // Data-only change: update node data in-place without re-layouting.
      // This preserves positions and avoids the O(n) layout pass.
      const dataMap = new Map(filteredData.nodes.map((n) => [n.id, n.data]));
      setNodes((prev) =>
        prev.map((n) => {
          const newData = dataMap.get(n.id);
          return newData ? { ...n, data: newData } : n;
        }),
      );
    }
  }, [filteredData, structureKey, setNodes, setEdges, autoFit]);

  // Separate effect: execute pending fitView whenever the instance is available.
  // This decouples fitView from the layout pass so it also fires when:
  //  - reactFlowInstance becomes available after layout already ran
  //  - new nodes stream in and the instance was already ready
  useEffect(() => {
    if (!pendingFitRef.current || !reactFlowInstance) return;
    pendingFitRef.current = false;

    // Triple-RAF: ReactFlow needs time to measure node dimensions after
    // setNodes. Double-RAF is often not enough for large graphs.
    let cancelled = false;
    const scheduleId = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (cancelled) return;
          reactFlowInstance.fitView({
            padding: 0.18,
            duration: 350,
            minZoom: 0.02,
            maxZoom: 1.5,
          });
        });
      });
    });
    return () => { cancelled = true; cancelAnimationFrame(scheduleId); };
  }, [reactFlowInstance, structureKey]);

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
    if (!reactFlowInstance) return;
    // Double-RAF ensures we run after the current layout pass has flushed
    // node positions to the DOM — otherwise fitView measures stale bounds
    // and the button appears to do nothing on large graphs.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        reactFlowInstance.fitView({
          padding: 0.2,
          duration: 500,
          minZoom: 0.05,
          maxZoom: 1.5,
        });
      });
    });
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
        onInit={(instance) => {
          setReactFlowInstance(instance);
          // If nodes were laid out before the instance was ready, trigger fitView now
          if (autoFit && filteredData.nodes.length > 0) {
            pendingFitRef.current = true;
          }
        }}
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
