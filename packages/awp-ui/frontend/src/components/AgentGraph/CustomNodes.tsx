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

export const customNodeTypes = {
  task: TaskNode,
  manager: ManagerNode,
  iteration: IterationNode,
  worker: WorkerNode,
  toolCall: ToolCallNode,
  completion: CompletionNode,
};
