import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import {
  Diamond,
  Star,
  RefreshCw,
  Circle,
  Triangle,
  Wrench,
  Layers,
  Settings,
  Sparkles,
} from 'lucide-react';
import clsx from 'clsx';
import { useWorkflowStore } from '@/stores/workflowStore';

// ---------------------------------------------------------------------------
// Confidence-badge colour mapping.
// Used for the top-right dot on WorkerNode. The colour scale matches the
// textual confidence % so a glance at the dot is consistent with the digits.
// ---------------------------------------------------------------------------

const CONFIDENCE_DOT_COLORS = {
  green: '#00E676',
  amber: '#FFD600',
  red: '#FF5252',
  grey: '#30363d',
} as const;

function confidenceDotColor(c: number | undefined): string {
  if (c === undefined) return CONFIDENCE_DOT_COLORS.grey;
  if (c >= 0.8) return CONFIDENCE_DOT_COLORS.green;
  if (c >= 0.5) return CONFIDENCE_DOT_COLORS.amber;
  return CONFIDENCE_DOT_COLORS.red;
}

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

// ---------------------------------------------------------------------------
// Live-progress visuals
// ---------------------------------------------------------------------------
// `runningOuterClasses` and `activePathOuterClasses` are applied to every
// node's outer wrapper so the user can tell at a glance:
//   - which node is *actively executing right now* (bright pulsing blue glow)
//   - which branch leads down to that execution point (softer blue tint)
//   - which nodes are finished (plain look, no extra highlight)
//
// The effect is additive: a running node gets both the ancestor tint AND the
// pulse. Finished-and-off-path nodes get nothing extra. Topology is not
// touched — only styling.

function runningOuterClasses(status: string | undefined): string {
  if (status !== 'running') return '';
  return 'animate-pulse [filter:drop-shadow(0_0_12px_rgba(64,196,255,0.55))]';
}

function activePathOuterClasses(
  onActivePath: boolean | undefined,
  status: string | undefined,
): string {
  if (!onActivePath || status === 'running') return '';
  return '[filter:drop-shadow(0_0_6px_rgba(64,196,255,0.25))]';
}

function runningBorderRing(status: string | undefined): string {
  return status === 'running'
    ? 'ring-2 ring-awp-blue/60 shadow-lg shadow-awp-blue/30'
    : '';
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
  const onActivePath = Boolean(data.onActivePath);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
        runningOuterClasses(data.status),
        activePathOuterClasses(onActivePath, data.status),
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
          runningBorderRing(data.status),
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
  const onActivePath = Boolean(data.onActivePath);

  // Read the optimizer-epoch context for the current run. If the run is not
  // part of any optimizer epoch, outerLoopContext is null and the pill is
  // omitted entirely — this is the normal case for ad-hoc runs.
  const outerLoopContext = useWorkflowStore((s) => s.outerLoopContext);
  const pillEntries = artifactPillEntries(outerLoopContext?.child_artifacts);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
        runningOuterClasses(data.status),
        activePathOuterClasses(onActivePath, data.status),
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-purple !border-awp-panel !w-2 !h-2" />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-xl border-2 bg-awp-panel px-5 py-3 min-w-[150px]',
          selected
            ? 'border-awp-purple ring-2 ring-awp-purple/30 shadow-lg shadow-awp-purple/20'
            : 'border-awp-purple/60 hover:border-awp-purple hover:shadow-md hover:shadow-awp-purple/10',
          runningBorderRing(data.status),
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
        {pillEntries && (
          <button
            type="button"
            onClick={(e) => {
              // Stop the parent's onClick from firing first — the pill should
              // route to the inspector without also toggling node selection.
              e.stopPropagation();
              selectNode(id);
            }}
            className="mt-1 flex items-center gap-1 rounded-full border border-awp-purple/40 bg-awp-purple/10 px-2 py-0.5 text-[10px] text-awp-purple hover:bg-awp-purple/20 hover:border-awp-purple/70 transition-colors"
            title="Open optimizer context in inspector"
            data-testid="manager-artifact-pill"
          >
            <Sparkles className="h-2.5 w-2.5" />
            <span className="font-mono">{pillEntries}</span>
          </button>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-awp-purple !border-awp-panel !w-2 !h-2" />
    </div>
  );
});

/** Build the artifact-version pill label.
 *
 * Rules (per Phase B3 spec):
 * - Only list artifacts whose version is greater than 0 (v0 is the default,
 *   suppressed).
 * - Max 3 artifacts listed; surplus collapses to "+N more".
 * - Returns null if no artifact qualifies — the pill is omitted entirely.
 */
export function artifactPillEntries(
  artifacts: Record<string, number> | undefined,
): string | null {
  if (!artifacts) return null;
  const entries = Object.entries(artifacts).filter(([, v]) => v > 0);
  if (entries.length === 0) return null;
  const shortName = (name: string) => name.split('.').pop()?.replace(/_/g, ' ') ?? name;
  const visible = entries.slice(0, 3).map(([n, v]) => `${shortName(n)} v${v}`);
  const remainder = entries.length - visible.length;
  return remainder > 0
    ? `${visible.join(' \u00b7 ')} +${remainder} more`
    : visible.join(' \u00b7 ');
}

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
  const onActivePath = Boolean(data.onActivePath);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
        runningOuterClasses(data.status),
        activePathOuterClasses(onActivePath, data.status),
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-yellow !border-awp-panel !w-2 !h-2" />

      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-2xl border-2 bg-awp-panel px-4 py-3 min-w-[130px]',
          colors.border,
          selected && `ring-2 ${colors.ring} shadow-lg ${colors.shadow}`,
          !selected && 'hover:shadow-md',
          runningBorderRing(data.status),
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
  // For a running worker, confidence is not yet meaningful — override the
  // border color to the live-blue so the circle reads as "in flight" rather
  // than "unknown confidence" (which would render grey and look abandoned).
  const borderColor = data.status === 'running'
    ? 'border-awp-blue'
    : confidenceBorderColor(data.confidence);
  const onActivePath = Boolean(data.onActivePath);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
        runningOuterClasses(data.status),
        activePathOuterClasses(onActivePath, data.status),
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-cyan !border-awp-panel !w-2 !h-2" />

      <div
        className={clsx(
          'relative flex flex-col items-center justify-center rounded-full border-2 bg-awp-panel min-w-[100px] min-h-[100px] p-4',
          borderColor,
          selected && 'ring-2 ring-awp-cyan/30 shadow-lg shadow-awp-cyan/20',
          !selected && 'hover:shadow-md',
          runningBorderRing(data.status),
          'transition-all duration-200',
        )}
      >
        {/* Confidence badge: glance-level dot in top-right corner. Supplements
            (does not replace) the textual percentage below. */}
        <span
          className="absolute top-1.5 right-1.5 h-2.5 w-2.5 rounded-full border border-awp-panel shadow-sm"
          style={{ backgroundColor: confidenceDotColor(data.confidence) }}
          title={
            data.confidence === undefined
              ? 'confidence unknown'
              : `confidence ${(data.confidence * 100).toFixed(0)}%`
          }
          data-testid="worker-confidence-dot"
        />
        <div className="flex items-center gap-1.5 mb-1">
          <Circle className={clsx('h-3 w-3 fill-current', confidenceColor(data.confidence))} />
          {statusDot(data.status)}
        </div>
        <span className="text-[11px] font-medium text-awp-text text-center max-w-[80px] truncate">
          {data.label}
        </span>
        {/* A running worker shows a bold LIVE pill instead of a premature
            confidence percentage (its result.json hasn't landed yet). Once
            complete, confidence replaces the pill so the final quality signal
            is always visible. */}
        {data.status === 'running' ? (
          <span className="mt-0.5 text-[9px] font-semibold uppercase tracking-wider px-1.5 rounded-full bg-awp-blue/20 text-awp-blue animate-pulse">
            live
          </span>
        ) : data.confidence !== undefined && (
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
  const onActivePath = Boolean(data.onActivePath);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-110',
        selected && 'scale-110',
        runningOuterClasses(data.status),
        activePathOuterClasses(onActivePath, data.status),
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
// SubmanagerNode -- A4 recursive delegation. Visually distinct from a worker:
// hexagon-feel via doubled border + Layers icon + depth badge. Sub-runs are
// rendered recursively beneath this node by the graph builder.
// ---------------------------------------------------------------------------

export const SubmanagerNode = memo(function SubmanagerNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const borderColor = data.status === 'running'
    ? 'border-awp-blue'
    : confidenceBorderColor(data.confidence);
  const dataAny = data as Record<string, unknown>;
  const depth: string = String(dataAny.submanagerDepth ?? '?');
  const failed: boolean = Boolean(dataAny.submanager_failed) || Boolean(data.hasError);
  const onActivePath = Boolean(data.onActivePath);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
        runningOuterClasses(data.status),
        activePathOuterClasses(onActivePath, data.status),
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
            runningBorderRing(data.status),
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

// ---------------------------------------------------------------------------
// ToolDefNode -- Represents a dynamically created tool definition. Distinct
// from ToolCallNode (which is a single invocation): a toolDef shows that the
// tool was *built* by the manager, even if no worker has called it yet.
// ---------------------------------------------------------------------------

export const ToolDefNode = memo(function ToolDefNode({ id, data }: NodeProps<NodeData>) {
  const selected = useIsSelected(id);
  const selectNode = useSelectNode();
  const called = Boolean((data as Record<string, unknown>).called);

  return (
    <div
      onClick={() => selectNode(id)}
      className={clsx(
        'group relative cursor-pointer transition-all duration-200 hover:scale-105',
        selected && 'scale-105',
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-awp-cyan !border-awp-panel !w-1.5 !h-1.5" />
      <div
        className={clsx(
          'flex flex-col items-center justify-center rounded-lg border-2 border-dashed bg-awp-panel px-3 py-2 min-w-[110px]',
          called ? 'border-awp-cyan/70' : 'border-awp-muted/50',
          selected && 'ring-2 ring-awp-cyan/30 shadow-lg shadow-awp-cyan/20',
          'transition-all duration-200',
        )}
      >
        <div className="flex items-center gap-1.5">
          <Settings className={clsx('h-3 w-3', called ? 'text-awp-cyan' : 'text-awp-muted')} />
          <span className="text-[9px] uppercase tracking-wide text-awp-muted">tool def</span>
        </div>
        <span className="mt-0.5 text-[10px] font-medium text-awp-text text-center max-w-[100px] truncate">
          {data.label}
        </span>
        {!called && (
          <span className="mt-0.5 text-[9px] text-awp-muted italic">unused</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-awp-cyan !border-awp-panel !w-1.5 !h-1.5" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// EpochMarkerNode -- decorative full-width banner inserted between epoch
// blocks on the /suites/{id}/graph view. Non-interactive: it carries
// metadata (epoch_num, mean_loss, artifact delta) but has no click handler
// and no handles, so React Flow treats it as pure chrome.
// ---------------------------------------------------------------------------

export const EpochMarkerNode = memo(function EpochMarkerNode(
  { data }: NodeProps<NodeData>,
) {
  const epochNum = (data as Record<string, unknown>).epoch_num;
  const suiteName = (data as Record<string, unknown>).suite_name as
    | string
    | undefined;
  const meanLoss = (data as Record<string, unknown>).mean_loss as
    | number
    | null
    | undefined;
  const delta = (data as Record<string, unknown>).delta as string | undefined;

  const meanLossLabel =
    meanLoss === null || meanLoss === undefined
      ? 'pending'
      : meanLoss.toFixed(3);

  return (
    <div
      className="flex h-full w-full items-center gap-3 rounded-md border border-dashed border-awp-muted/40 bg-awp-muted/5 px-4"
      data-testid="epoch-marker"
    >
      <span className="text-[11px] font-semibold uppercase tracking-wide text-awp-muted">
        Epoch {String(epochNum ?? '?')}
      </span>
      {suiteName && (
        <span className="text-[11px] text-awp-muted/80">{suiteName}</span>
      )}
      <span className="text-[11px] text-awp-muted/80">
        mean_loss={meanLossLabel}
      </span>
      {delta && (
        <span className="text-[11px] font-mono text-awp-muted/70">
          &Delta; {delta}
        </span>
      )}
    </div>
  );
});

export const customNodeTypes = {
  task: TaskNode,
  manager: ManagerNode,
  iteration: IterationNode,
  worker: WorkerNode,
  submanager: SubmanagerNode,
  toolCall: ToolCallNode,
  toolDef: ToolDefNode,
  epochMarker: EpochMarkerNode,
};
