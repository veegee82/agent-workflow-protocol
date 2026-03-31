import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import { useWorkflowStore } from '@/stores/workflowStore';
import { customNodeTypes } from './CustomNodes';

// ---------------------------------------------------------------------------
// Enhanced layout with better spacing and grouping
// ---------------------------------------------------------------------------

function layoutNodes(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  const inDegree = new Map<string, number>();
  const children = new Map<string, string[]>();
  for (const n of nodes) {
    inDegree.set(n.id, 0);
    children.set(n.id, []);
  }
  for (const e of edges) {
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
    const ch = children.get(e.source);
    if (ch) ch.push(e.target);
  }

  const layers: string[][] = [];
  const visited = new Set<string>();
  let queue = nodes.filter((n) => (inDegree.get(n.id) ?? 0) === 0).map((n) => n.id);

  while (queue.length > 0) {
    layers.push(queue);
    queue.forEach((id) => visited.add(id));
    const next: string[] = [];
    for (const id of queue) {
      for (const child of children.get(id) ?? []) {
        if (!visited.has(child) && !next.includes(child)) {
          const parentsDone = edges
            .filter((e) => e.target === child)
            .every((e) => visited.has(e.source));
          if (parentsDone) next.push(child);
        }
      }
    }
    if (next.length === 0) {
      const remaining = nodes.filter((n) => !visited.has(n.id)).map((n) => n.id);
      if (remaining.length > 0) { queue = remaining; continue; }
    }
    queue = next;
  }

  const xGap = 260;
  const yGap = 180;
  const nodePositions = new Map<string, { x: number; y: number }>();

  for (let row = 0; row < layers.length; row++) {
    const layer = layers[row];
    const totalWidth = (layer.length - 1) * xGap;
    const startX = -totalWidth / 2;
    for (let col = 0; col < layer.length; col++) {
      nodePositions.set(layer[col], { x: startX + col * xGap, y: row * yGap });
    }
  }

  return nodes.map((n) => ({
    ...n,
    position: nodePositions.get(n.id) ?? n.position,
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
    total: nodes.length, tasks: 0, managers: 0, iterations: 0,
    workers: 0, toolCalls: 0, completions: 0, running: 0, complete: 0, errors: 0,
  };
  for (const n of nodes) {
    const nt = n.data?.nodeType ?? n.type;
    const st = n.data?.status;
    if (nt === 'task') stats.tasks++;
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
}: {
  filters: FilterState;
  setFilters: React.Dispatch<React.SetStateAction<FilterState>>;
  onFitView: () => void;
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

function NodeTooltip({ node, position }: { node: Node; position: { x: number; y: number } }) {
  const data = node.data ?? {};
  const nodeType = data.nodeType ?? node.type ?? 'unknown';
  const status = data.status ?? 'pending';
  const confidence = data.confidence as number | undefined;
  const label = data.label ?? node.id;
  const error = data.error as string | undefined;
  const tools = data.tools_used as string[] | undefined;
  const toolCount = data.toolCount as number | undefined;

  const typeColors: Record<string, string> = {
    task: 'border-awp-blue/60',
    manager: 'border-awp-purple/60',
    iteration: 'border-awp-yellow/60',
    worker: 'border-awp-cyan/60',
    toolCall: 'border-awp-green/60',
    completion: 'border-awp-green/60',
  };

  return (
    <div
      className={clsx(
        'fixed z-50 pointer-events-none animate-fade-in',
        'rounded-xl bg-awp-panel/95 backdrop-blur-md border shadow-2xl',
        'px-4 py-3 min-w-[200px] max-w-[320px]',
        typeColors[nodeType] ?? 'border-awp-border/60',
      )}
      style={{ left: position.x + 16, top: position.y - 12 }}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-xs font-semibold text-awp-text">{label}</span>
        <StatusBadge status={status} />
      </div>

      <div className="text-[10px] text-awp-muted uppercase tracking-wider mb-1">
        {nodeType}
      </div>

      {confidence !== undefined && (
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-[10px] text-awp-muted">Confidence</span>
          <ConfidenceBar value={confidence} />
          <span className={clsx(
            'text-[11px] font-mono font-bold tabular-nums',
            confidence >= 0.8 ? 'text-awp-green' : confidence >= 0.5 ? 'text-awp-yellow' : 'text-awp-red',
          )}>
            {(confidence * 100).toFixed(0)}%
          </span>
        </div>
      )}

      {(tools && tools.length > 0) && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {tools.slice(0, 5).map((t, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-md bg-awp-bg/80 px-1.5 py-0.5 text-[9px] text-awp-green font-mono">
              <Wrench className="h-2 w-2" /> {t}
            </span>
          ))}
          {tools.length > 5 && (
            <span className="text-[9px] text-awp-muted">+{tools.length - 5} more</span>
          )}
        </div>
      )}

      {toolCount !== undefined && !tools && (
        <div className="mt-1 text-[10px] text-awp-muted">
          {toolCount} tool call{toolCount !== 1 ? 's' : ''}
        </div>
      )}

      {error && (
        <div className="mt-1.5 rounded-md bg-awp-red/10 border border-awp-red/20 px-2 py-1">
          <span className="text-[10px] text-awp-red line-clamp-2">{error}</span>
        </div>
      )}
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

  // Layout and style
  useEffect(() => {
    const mapped = filteredData.nodes.map((n) => ({
      ...n,
      type: n.data?.nodeType ?? 'task',
    }));
    const laid = layoutNodes(mapped, filteredData.edges);
    setNodes(laid);
    setEdges(styledEdges(filteredData.edges, laid));
  }, [filteredData, setNodes, setEdges]);

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
