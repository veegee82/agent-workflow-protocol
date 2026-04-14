import React, { useCallback, useEffect, useMemo } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
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

function layoutNodes(nodes: Node[], _edges: Edge[]): Node[] {
  // Trust backend positions if they look correct (multiple distinct x values).
  // Otherwise apply column layout for event-based nodes.
  if (nodes.length === 0) return nodes;
  const mgrs = nodes.filter((n) => (n.data as Record<string, unknown>)?.nodeType === 'manager');
  const xs = new Set(mgrs.map((n) => n.position.x));
  if (xs.size > 1 || (mgrs.length <= 1 && nodes.some((n) => n.position.x > 100))) return nodes;

  // Delegate to GraphVisPanel's layout (both components share the same logic)
  return nodes;
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
// Inner component (needs ReactFlowProvider context for fitBounds)
// ---------------------------------------------------------------------------

function AgentGraphInner() {
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
    <div className="relative h-full w-full">
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

export function AgentGraph() {
  return (
    <ReactFlowProvider>
      <AgentGraphInner />
    </ReactFlowProvider>
  );
}
