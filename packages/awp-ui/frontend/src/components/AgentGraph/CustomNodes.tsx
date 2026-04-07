import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import {
  Diamond,
  Star,
  RefreshCw,
  Circle,
  Triangle,
  CheckSquare,
  Wrench,
  Layers,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import clsx from 'clsx';
import { useWorkflowStore } from '@/stores/workflowStore';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function confidenceColor(c: number | undefined): string {
  if (c === undefined) return 'text-awp-muted';
  if (c >= 0.8) return 'text-awp-green';
  if (c >= 0.5) return 'text-awp-yellow';
  if (c >= 0.3) return 'text-awp-orange';
  return 'text-awp-red';
}

function confidenceBorderColor(c: number | undefined): string {
  if (c === undefined) return 'border-awp-muted';
  if (c >= 0.8) return 'border-awp-green';
  if (c >= 0.5) return 'border-awp-yellow';
  if (c >= 0.3) return 'border-awp-orange';
  return 'border-awp-red';
}

function statusDot(status: string) {
  const colors: Record<string, string> = {
    running: 'bg-awp-blue',
    complete: 'bg-awp-green',
    error: 'bg-awp-red',
    pending: 'bg-awp-muted',
  };
  return (
    <span className="relative flex h-2 w-2">
      {status === 'running' && (
        <span className={clsx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-75', colors[status])} />
      )}
      <span className={clsx('relative inline-flex h-2 w-2 rounded-full', colors[status] ?? 'bg-awp-muted')} />
    </span>
  );
}

interface NodeData {
  label: string;
  nodeType: string;
  status: string;
  confidence?: number;
  model?: string;
  decision?: string;
  iteration?: number;
  toolCount?: number;
  toolName?: string;
  iterationCount?: number;
  [key: string]: unknown;
}

function useIsSelected(id: string): boolean {
  return useWorkflowStore((s) => s.selectedNodeId === id);
}

function useSelectNode() {
  return useWorkflowStore((s) => s.selectNode);
}

// ---------------------------------------------------------------------------
// TaskNode -- Diamond shape
// ---------------------------------------------------------------------------

export const TaskNode = memo(function TaskNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-blue !border-awp-panel !w-2 !h-2" />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-lg border-2 bg-awp-panel px-4 py-3 min-w-[140px]',
          'rotate-0',
          selected
            ? 'border-awp-blue ring-2 ring-awp-blue/30 shadow-lg shadow-awp-blue/20'
            : 'border-awp-blue/60 hover:border-awp-blue hover:shadow-md hover:shadow-awp-blue/10',
          'transition-all duration-200',
        )}
      >
        <div className="flex items-center gap-2 mb-1">
          <Diamond className="h-3.5 w-3.5 text-awp-blue" />
          {statusDot(data.status)}
        </div>
        <span className="text-xs font-medium text-awp-text text-center max-w-[120px] truncate">
          {data.label}
        </span>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-awp-blue !border-awp-panel !w-2 !h-2" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// ManagerNode -- Star/pentagon shape, purple
// ---------------------------------------------------------------------------

export const ManagerNode = memo(function ManagerNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-purple !border-awp-panel !w-2 !h-2" />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-xl border-2 bg-awp-panel px-5 py-3 min-w-[150px]',
          selected
            ? 'border-awp-purple ring-2 ring-awp-purple/30 shadow-lg shadow-awp-purple/20'
            : 'border-awp-purple/60 hover:border-awp-purple hover:shadow-md hover:shadow-awp-purple/10',
          'transition-all duration-200',
        )}
      >
        <div className="flex items-center gap-2 mb-1">
          <Star className="h-4 w-4 text-awp-purple fill-awp-purple/30" />
          {statusDot(data.status)}
        </div>
        <span className="text-xs font-semibold text-awp-text">{data.label}</span>
        {data.model && (
          <span className="mt-0.5 text-[10px] text-awp-muted truncate max-w-[130px]">
            {String(data.model)}
          </span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-awp-purple !border-awp-panel !w-2 !h-2" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// IterationNode -- Rounded box, color by decision
// ---------------------------------------------------------------------------

function iterationColor(decision?: string): {
  border: string;
  ring: string;
  shadow: string;
  icon: string;
} {
  switch (decision) {
    case 'delegate':
      return {
        border: 'border-awp-yellow',
        ring: 'ring-awp-yellow/30',
        shadow: 'shadow-awp-yellow/20',
        icon: 'text-awp-yellow',
      };
    case 'complete':
      return {
        border: 'border-awp-green',
        ring: 'ring-awp-green/30',
        shadow: 'shadow-awp-green/20',
        icon: 'text-awp-green',
      };
    case 'fail':
      return {
        border: 'border-awp-red',
        ring: 'ring-awp-red/30',
        shadow: 'shadow-awp-red/20',
        icon: 'text-awp-red',
      };
    default:
      return {
        border: 'border-awp-yellow/60',
        ring: 'ring-awp-yellow/20',
        shadow: 'shadow-awp-yellow/10',
        icon: 'text-awp-yellow',
      };
  }
}

export const IterationNode = memo(function IterationNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const colors = iterationColor(data.decision);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-yellow !border-awp-panel !w-2 !h-2" />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-2xl border-2 bg-awp-panel px-4 py-3 min-w-[130px]',
          colors.border,
          selected && `ring-2 ${colors.ring} shadow-lg ${colors.shadow}`,
          !selected && 'hover:shadow-md',
          'transition-all duration-200',
        )}
      >
        <div className="flex items-center gap-2 mb-1">
          <RefreshCw className={clsx('h-3.5 w-3.5', colors.icon)} />
          {statusDot(data.status)}
        </div>
        <span className="text-xs font-medium text-awp-text">
          Iter {data.iteration ?? '?'}
        </span>
        {data.confidence !== undefined && (
          <span className={clsx('mt-0.5 text-[10px] font-mono', confidenceColor(data.confidence))}>
            {(data.confidence * 100).toFixed(0)}%
          </span>
        )}
        {typeof data.eval_score === 'number' && (
          <span
            className={clsx(
              'mt-0.5 text-[9px] font-mono px-1.5 rounded-full',
              data.eval_score >= 0.75 ? 'bg-emerald-500/20 text-emerald-400'
                : data.eval_score >= 0.5 ? 'bg-yellow-500/20 text-yellow-400'
                  : 'bg-red-500/20 text-red-400',
            )}
          >
            eval {(data.eval_score * 100).toFixed(0)}%
          </span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-awp-yellow !border-awp-panel !w-2 !h-2" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// WorkerNode -- Circle, color by confidence
// ---------------------------------------------------------------------------

export const WorkerNode = memo(function WorkerNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const borderColor = confidenceBorderColor(data.confidence);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-cyan !border-awp-panel !w-2 !h-2" />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-full border-2 bg-awp-panel min-w-[100px] min-h-[100px] p-4',
          borderColor,
          selected && 'ring-2 ring-awp-cyan/30 shadow-lg shadow-awp-cyan/20',
          !selected && 'hover:shadow-md',
          'transition-all duration-200',
        )}
      >
        <div className="flex items-center gap-1.5 mb-1">
          <Circle className={clsx('h-3 w-3 fill-current', confidenceColor(data.confidence))} />
          {statusDot(data.status)}
        </div>
        <span className="text-[11px] font-medium text-awp-text text-center max-w-[80px] truncate">
          {data.label}
        </span>
        {data.confidence !== undefined && (
          <span className={clsx('text-[10px] font-mono', confidenceColor(data.confidence))}>
            {(data.confidence * 100).toFixed(0)}%
          </span>
        )}
        {data.toolCount !== undefined && (
          <span className="mt-0.5 text-[9px] text-awp-muted">
            {data.toolCount} tool{Number(data.toolCount) !== 1 ? 's' : ''}
          </span>
        )}
        {typeof data.eval_score === 'number' && (
          <span
            className={clsx(
              'mt-0.5 text-[9px] font-mono px-1 rounded',
              data.eval_score >= 0.75 ? 'bg-emerald-500/20 text-emerald-400'
                : data.eval_score >= 0.5 ? 'bg-yellow-500/20 text-yellow-400'
                  : 'bg-red-500/20 text-red-400',
            )}
          >
            eval {(data.eval_score * 100).toFixed(0)}%
          </span>
        )}
        {typeof data.critique_score === 'number' && (
          <span
            className={clsx(
              'mt-0.5 text-[9px] font-mono px-1 rounded flex items-center gap-0.5',
              data.critique_score >= 0.8 ? 'bg-emerald-500/20 text-emerald-400'
                : data.critique_score >= 0.5 ? 'bg-amber-500/20 text-amber-400'
                  : 'bg-rose-500/20 text-rose-400',
            )}
          >
            {Array.isArray(data.critique_repairs) && data.critique_repairs.length > 0 && (
              <RefreshCw className="h-2.5 w-2.5" />
            )}
            critique {(data.critique_score * 100).toFixed(0)}%
          </span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-awp-cyan !border-awp-panel !w-2 !h-2" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// ToolCallNode -- Small triangle, green=ok red=failed
// ---------------------------------------------------------------------------

export const ToolCallNode = memo(function ToolCallNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const isError = data.status === 'error';

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-110',
        selected && 'scale-110',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-green !border-awp-panel !w-1.5 !h-1.5" />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-lg border-2 bg-awp-panel px-3 py-2 min-w-[90px]',
          isError
            ? 'border-awp-red/60'
            : data.status === 'complete'
              ? 'border-awp-green/60'
              : 'border-awp-blue/40',
          selected && (isError ? 'ring-2 ring-awp-red/30' : 'ring-2 ring-awp-green/30'),
          'transition-all duration-200',
        )}
      >
        <div className="flex items-center gap-1.5">
          {isError ? (
            <Triangle className="h-3 w-3 text-awp-red fill-awp-red/20" />
          ) : (
            <Wrench className="h-3 w-3 text-awp-green" />
          )}
          {statusDot(data.status)}
        </div>
        <span className="mt-0.5 text-[10px] font-medium text-awp-text text-center max-w-[80px] truncate">
          {data.label}
        </span>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-awp-green !border-awp-panel !w-1.5 !h-1.5" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// CompletionNode -- Box, green=success red=failure
// ---------------------------------------------------------------------------

export const CompletionNode = memo(function CompletionNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const isError = data.status === 'error';

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
      )}
    >
      <Handle type="target" position={Position.Top} className={clsx('!border-awp-panel !w-2 !h-2', isError ? '!bg-awp-red' : '!bg-awp-green')} />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-lg border-2 bg-awp-panel px-5 py-3 min-w-[140px]',
          isError ? 'border-awp-red' : 'border-awp-green',
          selected && (isError ? 'ring-2 ring-awp-red/30 shadow-lg shadow-awp-red/20' : 'ring-2 ring-awp-green/30 shadow-lg shadow-awp-green/20'),
          'transition-all duration-200',
        )}
      >
        <div className="flex items-center gap-2 mb-1">
          <CheckSquare className={clsx('h-4 w-4', isError ? 'text-awp-red' : 'text-awp-green')} />
        </div>
        <span className={clsx('text-xs font-semibold', isError ? 'text-awp-red' : 'text-awp-green')}>
          {isError ? 'Failed' : 'Complete'}
        </span>
        {data.iterationCount !== undefined && (
          <span className="mt-0.5 text-[10px] text-awp-muted">
            {data.iterationCount} iteration{Number(data.iterationCount) !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className={clsx('!border-awp-panel !w-2 !h-2', isError ? '!bg-awp-red' : '!bg-awp-green')} />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Node type registry for React Flow
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// SubRunClusterNode -- A4 recursive delegation. Big translucent container
// that visually groups everything that belongs to a single sub-run. Header
// shows the triggering worker, depth, model and budget summary. The actual
// child nodes (nested manager, iterations, workers, tool calls) are placed
// inside this node via React Flow's parentNode mechanism.
// ---------------------------------------------------------------------------

export const SubRunClusterNode = memo(function SubRunClusterNode({ id, data }: NodeProps<NodeData>) {
  // React Flow passes the configured style on the node itself; we read it
  // from data.palette so we can recolour the header to match.
  const dataAny = data as Record<string, unknown>;
  const palette = (dataAny.palette as { border: string; bg: string; label: string }) || {
    border: '#7C3AED',
    bg: 'rgba(124,58,237,0.06)',
    label: '#A78BFA',
  };
  const depth = dataAny.depth as number | undefined;
  const subRunId = dataAny.sub_run_id as string | undefined;
  const triggering = dataAny.triggering_worker as string | undefined;
  const mgrModel = dataAny.manager_model as string | undefined;
  const budget = (dataAny.budget as Record<string, unknown>) || {};
  const descendants = (dataAny.descendant_count as number | undefined) ?? 0;
  const workers = (dataAny.worker_count as number | undefined) ?? 0;
  const iters = (dataAny.iteration_count as number | undefined) ?? 0;
  const nestedClusters = (dataAny.nested_cluster_count as number | undefined) ?? 0;
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const collapsed = useWorkflowStore((s) => s.collapsedClusters.has(id));
  const toggleCluster = useWorkflowStore((s) => s.toggleCluster);

  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        selectNode(id);
      }}
      className={clsx(
        'relative w-full h-full transition-all duration-200',
        selected && 'ring-2 ring-offset-2 ring-offset-transparent rounded-xl',
      )}
      style={{
        pointerEvents: 'all',
        boxShadow: selected
          ? `0 0 0 2px ${palette.border}, 0 0 24px ${palette.border}66`
          : `0 0 18px ${palette.border}22`,
        borderRadius: '12px',
      }}
    >
      {/* Header bar — sticks to the top of the cluster. Click toggles collapse. */}
      <div
        className={clsx(
          'absolute top-0 left-0 right-0 px-3 py-2 flex items-center justify-between cursor-pointer select-none',
          collapsed ? 'rounded-xl' : 'rounded-t-xl',
        )}
        style={{
          background: `linear-gradient(135deg, ${palette.bg}, ${palette.border}22)`,
          borderBottom: collapsed ? 'none' : `1px dashed ${palette.border}`,
          color: palette.label,
          height: collapsed ? '100%' : undefined,
        }}
        onClick={(e) => {
          e.stopPropagation();
          toggleCluster(id);
          selectNode(id);
        }}
        title={collapsed ? 'Expand sub-run' : 'Collapse sub-run'}
      >
        <div className="flex items-center gap-2 min-w-0">
          {collapsed ? (
            <ChevronRight className="h-4 w-4 shrink-0" style={{ color: palette.border }} />
          ) : (
            <ChevronDown className="h-4 w-4 shrink-0" style={{ color: palette.border }} />
          )}
          <Layers className="h-4 w-4 shrink-0" style={{ color: palette.border }} />
          <span className="font-semibold text-[12px] tracking-wide whitespace-nowrap">
            SUB · d{depth ?? '?'}
          </span>
          {triggering && (
            <span className="text-[11px] opacity-80 font-mono truncate">
              ⤷ {triggering}
            </span>
          )}
          {/* Compact badges — visible always so the collapsed chip stays informative */}
          <span
            className="ml-1 px-1.5 py-0.5 rounded text-[9px] font-mono flex items-center gap-1"
            style={{ background: `${palette.border}22`, color: palette.label }}
          >
            <span title="iterations">{iters}↻</span>
            <span title="workers">·{workers}◯</span>
            {nestedClusters > 0 && (
              <span title="nested submanagers">·{nestedClusters}⤵</span>
            )}
            <span title="total descendants">·{descendants}</span>
          </span>
        </div>
        {!collapsed && (
          <div className="flex items-center gap-3 text-[10px] opacity-80 font-mono">
            {mgrModel && <span className="truncate max-w-[140px]">{mgrModel}</span>}
            {budget && (budget as any).max_loops !== undefined && (
              <span>loops≤{String((budget as any).max_loops)}</span>
            )}
            {budget && (budget as any).max_total_tokens !== undefined && (
              <span>tok≤{String((budget as any).max_total_tokens)}</span>
            )}
          </div>
        )}
      </div>
      {/* Connection handles for the trigger edge from the parent worker */}
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: palette.border, borderColor: 'var(--awp-panel)' }}
        className="!w-2.5 !h-2.5"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: palette.border, borderColor: 'var(--awp-panel)' }}
        className="!w-2.5 !h-2.5"
      />
      {/* Sub-run id watermark in the bottom-right (only when expanded) */}
      {!collapsed && subRunId && (
        <div
          className="absolute bottom-1 right-2 text-[9px] font-mono opacity-50 pointer-events-none"
          style={{ color: palette.label }}
        >
          {subRunId}
        </div>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// SubmanagerNode -- A4 recursive delegation. Visually distinct from a worker:
// hexagon-feel via doubled border + Layers icon + depth badge. Sub-runs are
// rendered recursively beneath this node by the graph builder.
// ---------------------------------------------------------------------------

export const SubmanagerNode = memo(function SubmanagerNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const borderColor = confidenceBorderColor(data.confidence);
  const dataAny = data as Record<string, unknown>;
  const depth: string = String(dataAny.submanagerDepth ?? '?');
  const failed: boolean = Boolean(dataAny.submanager_failed) || Boolean(data.hasError);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-purple !border-awp-panel !w-2 !h-2" />

      {/* Outer ring to signal "this is a sub-loop, not a leaf worker" */}
      <div
        className={clsx(
          'rounded-2xl p-1 border-2 border-dashed',
          failed ? 'border-awp-red' : 'border-awp-purple/60',
        )}
      >
        <div
          className={clsx(
            'flex flex-col items-center justify-center rounded-xl border-2 bg-awp-panel min-w-[120px] min-h-[110px] p-3',
            borderColor,
            selected && 'ring-2 ring-awp-purple/40 shadow-lg shadow-awp-purple/20',
            !selected && 'hover:shadow-md',
            'transition-all duration-200',
          )}
        >
          <div className="flex items-center gap-1.5 mb-1">
            <Layers className="h-3.5 w-3.5 text-awp-purple" />
            {statusDot(data.status)}
            <span className="text-[9px] font-mono px-1 rounded bg-awp-purple/20 text-awp-purple">
              d{depth}
            </span>
          </div>
          <span className="text-[11px] font-medium text-awp-text text-center max-w-[100px] truncate">
            {data.label}
          </span>
          <span className="text-[9px] text-awp-purple/80 uppercase tracking-wide">
            submanager
          </span>
          {data.confidence !== undefined && (
            <span className={clsx('text-[10px] font-mono mt-0.5', confidenceColor(data.confidence))}>
              {(data.confidence * 100).toFixed(0)}%
            </span>
          )}
          {failed && (
            <span className="text-[9px] text-awp-red mt-0.5">failed</span>
          )}
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-awp-purple !border-awp-panel !w-2 !h-2" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Node type registry for React Flow
// ---------------------------------------------------------------------------

export const customNodeTypes = {
  task: TaskNode,
  manager: ManagerNode,
  iteration: IterationNode,
  worker: WorkerNode,
  submanager: SubmanagerNode,
  subRunCluster: SubRunClusterNode,
  toolCall: ToolCallNode,
  completion: CompletionNode,
};
