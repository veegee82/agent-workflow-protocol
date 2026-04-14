import { useMemo } from 'react';
import {
  Play,
  CheckCircle2,
  AlertCircle,
  Circle,
  Loader2,
} from 'lucide-react';
import clsx from 'clsx';
import { useWorkflowStore } from '@/stores/workflowStore';

// ---------------------------------------------------------------------------
// Status icon helper
// ---------------------------------------------------------------------------

function statusIcon(status: string) {
  switch (status) {
    case 'running':
      return <Loader2 className="h-3 w-3 text-awp-blue animate-spin" />;
    case 'complete':
      return <CheckCircle2 className="h-3 w-3 text-awp-green" />;
    case 'error':
    case 'failed':
      return <AlertCircle className="h-3 w-3 text-awp-red" />;
    case 'stopped':
      return <Circle className="h-3 w-3 text-awp-orange fill-awp-orange/30" />;
    default:
      return <Circle className="h-3 w-3 text-awp-muted" />;
  }
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

// ---------------------------------------------------------------------------
// RunSelector — horizontal scrollable bar of run chips
// ---------------------------------------------------------------------------

export function RunSelector() {
  const runHistory = useWorkflowStore((s) => s.runHistory);
  const currentRunId = useWorkflowStore((s) => s.currentRunId);
  const viewingRunId = useWorkflowStore((s) => s.viewingRunId);
  const setViewingRun = useWorkflowStore((s) => s.setViewingRun);
  const runStatus = useWorkflowStore((s) => s.runStatus);
  const activePanel = useWorkflowStore((s) => s.activePanel);

  // Don't show on History tab or when there are no runs
  const hidden = activePanel === 'history' || runHistory.length === 0;

  // Build ordered list: oldest first, live run highlighted
  const runs = useMemo(() => {
    const items = [...runHistory].reverse(); // API returns newest-first
    return items;
  }, [runHistory]);

  // Effective selection: null means live run
  const effectiveId = viewingRunId ?? currentRunId;

  if (hidden) return null;

  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-awp-border bg-awp-panel/60 backdrop-blur-sm overflow-x-auto shrink-0">
      <span className="text-[10px] font-semibold text-awp-muted uppercase tracking-wider shrink-0 mr-1">
        Runs
      </span>
      {runs.map((run, idx) => {
        const isLive = run.run_id === currentRunId && runStatus === 'running';
        const isViewing = run.run_id === effectiveId;

        return (
          <button
            key={run.run_id}
            onClick={() => setViewingRun(isLive ? null : run.run_id)}
            className={clsx(
              'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all shrink-0',
              isViewing
                ? 'bg-awp-blue/15 text-awp-blue ring-1 ring-awp-blue/30'
                : 'text-awp-muted hover:text-awp-text hover:bg-awp-border/40',
            )}
            title={`${run.task.slice(0, 80)}${run.task.length > 80 ? '...' : ''}`}
          >
            {isLive ? (
              <Play className="h-3 w-3 text-awp-blue fill-awp-blue/30" />
            ) : (
              statusIcon(run.status)
            )}
            <span className="font-mono">#{idx + 1}</span>
            {formatTime(run.created_at) && (
              <span className="text-[10px] opacity-60">{formatTime(run.created_at)}</span>
            )}
            {isLive && (
              <span className="text-[9px] px-1 py-0.5 rounded bg-awp-blue/20 text-awp-blue font-semibold uppercase">
                live
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
