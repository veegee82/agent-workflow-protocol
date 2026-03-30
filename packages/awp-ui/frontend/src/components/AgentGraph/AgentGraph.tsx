import React, { useCallback, useEffect, useMemo } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { GitBranch } from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { customNodeTypes } from './CustomNodes';

// ---------------------------------------------------------------------------
// Dagre-style auto-layout (simple hierarchical)
// ---------------------------------------------------------------------------

function layoutNodes(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  // Build adjacency for topological sort
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

  // BFS layers
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
          // Check if all parents visited
          const parentsDone = edges
            .filter((e) => e.target === child)
            .every((e) => visited.has(e.source));
          if (parentsDone) next.push(child);
        }
      }
    }

    // If nothing advanced, push remaining unvisited
    if (next.length === 0) {
      const remaining = nodes
        .filter((n) => !visited.has(n.id))
        .map((n) => n.id);
      if (remaining.length > 0) {
        queue = remaining;
        continue;
      }
    }
    queue = next;
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

export function AgentGraph() {
  const storeNodes = useWorkflowStore((s) => s.graphNodes);
  const storeEdges = useWorkflowStore((s) => s.graphEdges);
  const selectNode = useWorkflowStore((s) => s.selectNode);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Sync store -> local reactflow state with layout
  useEffect(() => {
    const mapped = storeNodes.map((n) => ({
      ...n,
      type: n.data?.nodeType ?? 'task',
    }));
    const laid = layoutNodes(mapped, storeEdges);
    setNodes(laid);
    setEdges(storeEdges.map(styledEdge));
  }, [storeNodes, storeEdges, setNodes, setEdges]);

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

  if (storeNodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-awp-muted">
        <GitBranch className="h-12 w-12 opacity-40" />
        <p className="text-sm">Agent graph will appear during execution</p>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
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
        minZoom={0.2}
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
          nodeColor={(n) => {
            const status = n.data?.status;
            if (status === 'running') return '#40C4FF';
            if (status === 'complete') return '#00E676';
            if (status === 'error') return '#FF1744';
            return '#8b949e';
          }}
          maskColor="rgba(13, 17, 23, 0.8)"
        />
      </ReactFlow>
    </div>
  );
}
