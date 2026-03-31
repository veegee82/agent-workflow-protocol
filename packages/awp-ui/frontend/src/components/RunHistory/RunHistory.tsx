import { useCallback, useEffect, useState } from 'react';
import {
  History,
  Search,
  Trash2,
  Clock,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Circle,
  Play,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import type { RunHistoryEntry } from '@/types';
import clsx from 'clsx';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatDuration(start: string, end?: string): string {
  if (!end) return 'In progress';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
  return `${Math.floor(ms / 3_600_000)}h ${Math.floor((ms % 3_600_000) / 60_000)}m`;
}

const statusConfig: Record<
  string,
  { color: string; icon: React.ReactNode; variant: string }
> = {
  running: {
    color: 'text-awp-blue',
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    variant: 'bg-awp-blue/15 text-awp-blue border-awp-blue/30',
  },
  complete: {
    color: 'text-awp-green',
    icon: <CheckCircle2 className="h-3 w-3" />,
    variant: 'bg-awp-green/15 text-awp-green border-awp-green/30',
  },
  error: {
    color: 'text-awp-red',
    icon: <AlertCircle className="h-3 w-3" />,
    variant: 'bg-awp-red/15 text-awp-red border-awp-red/30',
  },
  idle: {
    color: 'text-awp-muted',
    icon: <Circle className="h-3 w-3" />,
    variant: 'bg-awp-muted/15 text-awp-muted border-awp-muted/30',
  },
};

// ---------------------------------------------------------------------------
// Run entry card
// ---------------------------------------------------------------------------

function RunEntry({
  entry,
  onLoad,
  onDelete,
}: {
  entry: RunHistoryEntry;
  onLoad: () => void;
  onDelete: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const cfg = statusConfig[entry.status] ?? statusConfig.idle;

  return (
    <div className="group rounded-lg border border-awp-border bg-awp-bg hover:border-awp-blue/30 transition-colors">
      <button
        onClick={onLoad}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left"
      >
        <div className={clsx('mt-0.5 shrink-0', cfg.color)}>
          {cfg.icon}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-awp-text line-clamp-2">
            {entry.task}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-awp-muted">
            <span className="font-mono">{entry.model}</span>
            <span className="flex items-center gap-1">
              <Clock className="h-2.5 w-2.5" />
              {formatDuration(entry.created_at, entry.completed_at)}
            </span>
            <span>{formatDate(entry.created_at)}</span>
          </div>
        </div>
        <span
          className={clsx(
            'shrink-0 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
            cfg.variant,
          )}
        >
          {entry.status}
        </span>
      </button>

      {/* Action buttons */}
      <div className="flex items-center justify-end gap-1 border-t border-awp-border/30 px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onLoad}
          className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-awp-muted hover:text-awp-blue hover:bg-awp-blue/10 transition-colors"
        >
          <Play className="h-2.5 w-2.5" />
          Load
        </button>
        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-awp-red">Delete?</span>
            <button
              onClick={() => {
                onDelete();
                setConfirmDelete(false);
              }}
              className="rounded px-1.5 py-0.5 text-[10px] font-medium text-awp-red hover:bg-awp-red/10 transition-colors"
            >
              Yes
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="rounded px-1.5 py-0.5 text-[10px] text-awp-muted hover:text-awp-text transition-colors"
            >
              No
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-awp-muted hover:text-awp-red hover:bg-awp-red/10 transition-colors"
          >
            <Trash2 className="h-2.5 w-2.5" />
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export function RunHistory() {
  const { runHistory, loadHistory } = useWorkflowStore();
  const [search, setSearch] = useState('');

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const filtered = search.trim()
    ? runHistory.filter(
        (e) =>
          e.task.toLowerCase().includes(search.toLowerCase()) ||
          e.model.toLowerCase().includes(search.toLowerCase()) ||
          e.status.toLowerCase().includes(search.toLowerCase()),
      )
    : runHistory;

  const sorted = [...filtered].sort(
    (a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  const handleLoad = useCallback((_entry: RunHistoryEntry) => {
    // Placeholder: would load events + graph for this run via API
  }, []);

  const handleDelete = useCallback((_entry: RunHistoryEntry) => {
    // Placeholder: would delete run via API and refresh
  }, []);

  return (
    <div className="flex h-full flex-col">
      {/* Search bar */}
      <div className="border-b border-awp-border px-4 py-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-awp-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search runs..."
            className="w-full rounded-lg border border-awp-border bg-awp-bg pl-8 pr-3 py-1.5 text-xs text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
          />
        </div>
      </div>

      {/* Entries */}
      <div className="flex-1 overflow-y-auto p-4">
        {sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-awp-muted">
            <History className="h-10 w-10 opacity-40" />
            <p className="text-sm">
              {search.trim() ? 'No matching runs found' : 'No run history yet'}
            </p>
            <p className="text-[11px] text-awp-muted/60">
              {search.trim()
                ? 'Try a different search term'
                : 'Completed workflows will appear here'}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {sorted.map((entry) => (
              <RunEntry
                key={entry.run_id}
                entry={entry}
                onLoad={() => handleLoad(entry)}
                onDelete={() => handleDelete(entry)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
