import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  type Node,
  type Edge,
} from 'reactflow';
import 'reactflow/dist/style.css';
import {
  GitBranch,
  Layers,
  Maximize2,
  ChevronsDownUp,
  ChevronsUpDown,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react';
import clsx from 'clsx';
import { useWorkflowStore } from '@/stores/workflowStore';
import { customNodeTypes } from './CustomNodes';

// ---------------------------------------------------------------------------
// Dagre-style auto-layout (simple hierarchical)
// ---------------------------------------------------------------------------

function layoutNodes(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  // A4: when sub-run clusters are present, the backend has already laid out
  // every node hierarchically (parent-relative positions for cluster
  // children, absolute for the cluster anchors). Replacing those with our
  // top-down BFS layout would shred the cluster geometry. Trust the
  // backend layout in that case.
  const hasClusters = nodes.some(
    (n) => n.type === 'subRunCluster' || (n as any).parentNode,
  );
  if (hasClusters) {
    return nodes;
  }

  // Build adjacency for topological sort — O(n+e) using Maps
  const inDegree = new Map<string, number>();
  const children = new Map<string, string[]>();
  const parents = new Map<string, Set<string>>();
  for (const n of nodes) {
    inDegree.set(n.id, 0);
    children.set(n.id, []);
    parents.set(n.id, new Set());
  }
  for (const e of edges) {
    if (!inDegree.has(e.target) || !children.has(e.source)) continue;
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
    children.get(e.source)!.push(e.target);
    parents.get(e.target)!.add(e.source);
  }

  // BFS layers
  const layers: string[][] = [];
  const visited = new Set<string>();
  let queue = nodes.filter((n) => (inDegree.get(n.id) ?? 0) === 0).map((n) => n.id);

  while (queue.length > 0) {
    layers.push(queue);
    queue.forEach((id) => visited.add(id));

    const next = new Set<string>();
    for (const id of queue) {
      for (const child of children.get(id) ?? []) {
        if (!visited.has(child) && !next.has(child)) {
          // Check if all parents visited — O(1) per parent via Set
          const allParentsVisited = [...(parents.get(child) ?? [])].every(
            (p) => visited.has(p),
          );
          if (allParentsVisited) next.add(child);
        }
      }
    }

    // If nothing advanced, push remaining unvisited
    if (next.size === 0) {
      const remaining = nodes
        .filter((n) => !visited.has(n.id))
        .map((n) => n.id);
      if (remaining.length > 0) {
        queue = remaining;
        continue;
      }
    }
    queue = [...next];
  }

  // Assign positions
  const xGap = 220;
  const yGap = 150;
  const nodePositions = new Map<string, { x: number; y: number }>();

  for (let row = 0; row < layers.length; row++) {
    const layer = layers[row];
    const totalWidth = (layer.length - 1) * xGap;
    const startX = -totalWidth / 2;

    for (let col = 0; col < layer.length; col++) {
      nodePositions.set(layer[col], {
        x: startX + col * xGap,
        y: row * yGap,
      });
    }
  }

  return nodes.map((n) => ({
    ...n,
    position: nodePositions.get(n.id) ?? n.position,
  }));
}

// ---------------------------------------------------------------------------
// Edge default styles
// ---------------------------------------------------------------------------

function styledEdge(edge: Edge): Edge {
  const isRunning = edge.animated;
  return {
    ...edge,
    style: {
      stroke: isRunning ? '#40C4FF' : '#30363d',
      strokeWidth: 2,
      ...(edge.style ?? {}),
    },
    animated: isRunning,
    type: 'smoothstep',
  };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Cluster collapse: build a hidden-set from collapsed cluster ids by walking
// the parentNode chain. Any node whose ancestor chain crosses a collapsed
// cluster is hidden. Edges with a hidden endpoint are hidden too.
// ---------------------------------------------------------------------------

function applyClusterCollapse(
  nodes: Node[],
  edges: Edge[],
  collapsed: Set<string>,
): { nodes: Node[]; edges: Edge[] } {
  if (collapsed.size === 0) return { nodes, edges };

  const byId = new Map(nodes.map((n) => [n.id, n] as const));
  const hidden = new Set<string>();

  // A node is hidden iff one of its ancestors (parentNode chain) is in
  // `collapsed`. The cluster node itself stays visible (so its header chip
  // is still clickable), only its descendants disappear.
  for (const n of nodes) {
    let p = (n as any).parentNode as string | undefined;
    while (p) {
      if (collapsed.has(p)) {
        hidden.add(n.id);
        break;
      }
      const parent = byId.get(p);
      p = parent ? ((parent as any).parentNode as string | undefined) : undefined;
    }
  }

  // Compute a compact "chip" geometry for collapsed clusters so they don't
  // hog hundreds of pixels of empty canvas while their children are hidden.
  const COMPACT_W = 320;
  const COMPACT_H = 44;

  const newNodes = nodes
    .filter((n) => !hidden.has(n.id))
    .map((n) => {
      if (n.type === 'subRunCluster' && collapsed.has(n.id)) {
        return {
          ...n,
          style: {
            ...(n.style ?? {}),
            width: COMPACT_W,
            height: COMPACT_H,
          },
        };
      }
      return n;
    });

  const newEdges = edges.filter(
    (e) => !hidden.has(e.source) && !hidden.has(e.target),
  );

  return { nodes: newNodes, edges: newEdges };
}

// ---------------------------------------------------------------------------
// ClusterNavigator -- sidebar tree of all submanager clusters with click to
// focus + collapse toggle. Helps navigate huge graphs.
// ---------------------------------------------------------------------------

interface ClusterEntry {
  id: string;
  depth: number;
  label: string;
  triggering?: string;
  workers: number;
  iterations: number;
  descendants: number;
  paletteBorder: string;
}

function ClusterNavigator({
  open,
  onClose,
  onFocus,
}: {
  open: boolean;
  onClose: () => void;
  onFocus: (id: string) => void;
}) {
  const storeNodes = useWorkflowStore((s) => s.graphNodes);
  const collapsed = useWorkflowStore((s) => s.collapsedClusters);
  const toggleCluster = useWorkflowStore((s) => s.toggleCluster);
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId);

  const clusters: ClusterEntry[] = useMemo(() => {
    return storeNodes
      .filter((n) => n.type === 'subRunCluster')
      .map((n) => {
        const d = n.data as Record<string, unknown>;
        const palette = (d.palette as { border: string }) || { border: '#7C3AED' };
        return {
          id: n.id,
          depth: (d.depth as number) ?? 1,
          label: (d.sub_run_id as string) ?? n.id,
          triggering: d.triggering_worker as string | undefined,
          workers: (d.worker_count as number) ?? 0,
          iterations: (d.iteration_count as number) ?? 0,
          descendants: (d.descendant_count as number) ?? 0,
          paletteBorder: palette.border,
        };
      });
  }, [storeNodes]);

  if (!open || clusters.length === 0) return null;

  return (
    <div className="absolute top-3 right-3 z-20 w-72 max-h-[70%] flex flex-col rounded-xl border border-awp-border bg-awp-panel/95 backdrop-blur shadow-2xl overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-awp-border">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-awp-purple" />
          <span className="text-xs font-semibold text-awp-text">
            Submanagers ({clusters.length})
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-awp-muted hover:text-awp-text transition-colors"
          title="Hide navigator"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
      </div>
      <div className="overflow-y-auto flex-1 py-1">
        {clusters.map((c) => {
          const isCollapsed = collapsed.has(c.id);
          const isSelected = selectedNodeId === c.id;
          return (
            <div
              key={c.id}
              className={clsx(
                'group flex items-center gap-2 px-2 py-1.5 mx-1 rounded cursor-pointer transition-colors',
                isSelected
                  ? 'bg-awp-border/60'
                  : 'hover:bg-awp-border/30',
              )}
              style={{ paddingLeft: 8 + c.depth * 12 }}
              onClick={() => onFocus(c.id)}
            >
              <div
                className="w-1 h-6 rounded-full shrink-0"
                style={{ background: c.paletteBorder }}
              />
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  toggleCluster(c.id);
                }}
                className="text-awp-muted hover:text-awp-text shrink-0"
                title={isCollapsed ? 'Expand' : 'Collapse'}
              >
                {isCollapsed ? (
                  <ChevronsUpDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronsDownUp className="h-3.5 w-3.5" />
                )}
              </button>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-mono text-awp-text truncate">
                  d{c.depth} · {c.triggering ?? '?'}
                </div>
                <div className="text-[9px] text-awp-muted font-mono">
                  {c.iterations}↻ · {c.workers}◯ · {c.descendants} total
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inner component (needs ReactFlowProvider context for fitBounds)
// ---------------------------------------------------------------------------

function AgentGraphInner() {
  const storeNodes = useWorkflowStore((s) => s.graphNodes);
  const storeEdges = useWorkflowStore((s) => s.graphEdges);
  const selectNode = useWorkflowStore((s) => s.selectNode);
  const collapsed = useWorkflowStore((s) => s.collapsedClusters);
  const expandAll = useWorkflowStore((s) => s.expandAllClusters);
  const collapseAll = useWorkflowStore((s) => s.collapseAllClusters);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [navOpen, setNavOpen] = useState(true);
  const rf = useReactFlow();

  // Sync store -> local reactflow state with layout + collapse filtering
  useEffect(() => {
    const mapped = storeNodes.map((n) => ({
      ...n,
      type: n.data?.nodeType ?? 'task',
    }));
    const laid = layoutNodes(mapped, storeEdges);
    const filtered = applyClusterCollapse(laid, storeEdges, collapsed);
    setNodes(filtered.nodes);
    setEdges(filtered.edges.map(styledEdge));
  }, [storeNodes, storeEdges, collapsed, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      selectNode(node.id);
    },
    [selectNode],
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const nodeTypes = useMemo(() => customNodeTypes, []);

  // Focus a specific cluster: zoom into its bounding box. We compute the
  // bounding box from the cluster node itself (which carries width/height
  // in its style) plus its absolute position resolved through parents.
  const focusCluster = useCallback(
    (clusterId: string) => {
      const node = storeNodes.find((n) => n.id === clusterId);
      if (!node) return;
      // Resolve absolute position by walking parentNode chain
      let x = node.position?.x ?? 0;
      let y = node.position?.y ?? 0;
      let p = (node as any).parentNode as string | undefined;
      const byId = new Map(storeNodes.map((n) => [n.id, n] as const));
      while (p) {
        const parent = byId.get(p);
        if (!parent) break;
        x += parent.position?.x ?? 0;
        y += parent.position?.y ?? 0;
        p = (parent as any).parentNode as string | undefined;
      }
      const width =
        Number((node as any).style?.width) ||
        (collapsed.has(clusterId) ? 320 : 600);
      const height =
        Number((node as any).style?.height) ||
        (collapsed.has(clusterId) ? 44 : 400);
      rf.fitBounds(
        { x: x - 40, y: y - 40, width: width + 80, height: height + 80 },
        { duration: 600, padding: 0.2 },
      );
      selectNode(clusterId);
    },
    [rf, storeNodes, collapsed, selectNode],
  );

  if (storeNodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-awp-muted">
        <GitBranch className="h-12 w-12 opacity-40" />
        <p className="text-sm">Agent graph will appear during execution</p>
      </div>
    );
  }

  const hasClusters = storeNodes.some((n) => n.type === 'subRunCluster');

  return (
    <div className="relative h-full w-full">
      {/* Floating toolbar — top-left */}
      {hasClusters && (
        <div className="absolute top-3 left-3 z-20 flex items-center gap-1 rounded-lg border border-awp-border bg-awp-panel/95 backdrop-blur shadow-lg p-1">
          <button
            onClick={collapseAll}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-awp-muted hover:text-awp-text hover:bg-awp-border/40 transition-colors"
            title="Collapse all submanagers"
          >
            <ChevronsDownUp className="h-3.5 w-3.5" />
            collapse
          </button>
          <button
            onClick={expandAll}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-awp-muted hover:text-awp-text hover:bg-awp-border/40 transition-colors"
            title="Expand all submanagers"
          >
            <ChevronsUpDown className="h-3.5 w-3.5" />
            expand
          </button>
          <button
            onClick={() => rf.fitView({ duration: 500, padding: 0.2 })}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-awp-muted hover:text-awp-text hover:bg-awp-border/40 transition-colors"
            title="Fit graph to view"
          >
            <Maximize2 className="h-3.5 w-3.5" />
            fit
          </button>
          {!navOpen && (
            <button
              onClick={() => setNavOpen(true)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-awp-muted hover:text-awp-text hover:bg-awp-border/40 transition-colors"
              title="Show submanager navigator"
            >
              <PanelRightOpen className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color="#30363d"
          gap={20}
          size={1}
        />
        <Controls
          className="!bg-awp-panel !border-awp-border !rounded-lg !shadow-lg [&>button]:!bg-awp-panel [&>button]:!border-awp-border [&>button]:!text-awp-muted [&>button:hover]:!bg-awp-border [&>button:hover]:!text-awp-text"
          showInteractive={false}
        />
        <MiniMap
          className="!bg-awp-panel !border-awp-border !rounded-lg"
          pannable
          zoomable
          nodeColor={(n) => {
            if (n.type === 'subRunCluster') {
              const palette = (n.data as any)?.palette;
              return palette?.border ?? '#7C3AED';
            }
            const status = n.data?.status;
            if (status === 'running') return '#40C4FF';
            if (status === 'complete') return '#00E676';
            if (status === 'error') return '#FF1744';
            return '#8b949e';
          }}
          maskColor="rgba(13, 17, 23, 0.8)"
        />
      </ReactFlow>

      <ClusterNavigator
        open={navOpen && hasClusters}
        onClose={() => setNavOpen(false)}
        onFocus={focusCluster}
      />
    </div>
  );
}

export function AgentGraph() {
  return (
    <ReactFlowProvider>
      <AgentGraphInner />
    </ReactFlowProvider>
  );
}
