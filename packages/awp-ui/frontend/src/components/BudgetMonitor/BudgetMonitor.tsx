import React, { useState } from 'react';
import {
  RefreshCw,
  Coins,
  Clock,
  Users,
  Wrench,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import clsx from 'clsx';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTokens(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

function formatTime(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s >= 3600) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m}m`;
  }
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}m ${sec}s`;
  }
  return `${s}s`;
}

function pct(used: number, max: number): number {
  if (max <= 0) return 0;
  return Math.min(100, (used / max) * 100);
}

function barColor(percentage: number): string {
  if (percentage >= 90) return 'bg-awp-red';
  if (percentage >= 80) return 'bg-awp-orange';
  if (percentage >= 60) return 'bg-awp-yellow';
  return 'bg-awp-green';
}

function barTextColor(percentage: number): string {
  if (percentage >= 90) return 'text-awp-red';
  if (percentage >= 80) return 'text-awp-orange';
  if (percentage >= 60) return 'text-awp-yellow';
  return 'text-awp-green';
}

// ---------------------------------------------------------------------------
// Budget bar
// ---------------------------------------------------------------------------

interface BudgetBarProps {
  icon: React.ReactNode;
  label: string;
  used: number;
  max: number;
  format?: (v: number) => string;
  compact?: boolean;
}

function BudgetBar({
  icon,
  label,
  used,
  max,
  format = String,
  compact = false,
}: BudgetBarProps) {
  const percentage = pct(used, max);
  const isNearLimit = percentage >= 80;

  if (compact) {
    return (
      <div className="flex items-center gap-2 min-w-0">
        <span className={clsx('shrink-0', barTextColor(percentage))}>
          {icon}
        </span>
        <div className="flex-1 min-w-[60px]">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-awp-border">
            <div
              className={clsx(
                'h-full rounded-full transition-all duration-700 ease-out',
                barColor(percentage),
                isNearLimit && 'animate-pulse-slow',
              )}
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>
        <span className="shrink-0 text-[10px] font-mono text-awp-muted whitespace-nowrap">
          {format(used)}/{format(max)}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className={barTextColor(percentage)}>{icon}</span>
          <span className="text-xs font-medium text-awp-text">{label}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={clsx('text-xs font-mono', barTextColor(percentage))}>
            {format(used)}
          </span>
          <span className="text-xs text-awp-muted">/</span>
          <span className="text-xs font-mono text-awp-muted">{format(max)}</span>
          <span
            className={clsx(
              'ml-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
              percentage >= 90
                ? 'bg-awp-red/15 text-awp-red'
                : percentage >= 80
                  ? 'bg-awp-orange/15 text-awp-orange'
                  : percentage >= 60
                    ? 'bg-awp-yellow/15 text-awp-yellow'
                    : 'bg-awp-green/15 text-awp-green',
            )}
          >
            {percentage.toFixed(0)}%
          </span>
        </div>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-awp-border">
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-700 ease-out',
            barColor(percentage),
            isNearLimit && 'animate-pulse-slow',
          )}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact mode (for TopBar)
// ---------------------------------------------------------------------------

export function BudgetMonitorCompact() {
  const budget = useWorkflowStore((s) => s.budget);
  const runStatus = useWorkflowStore((s) => s.runStatus);

  if (runStatus === 'idle') return null;

  return (
    <div className="flex items-center gap-3">
      <BudgetBar
        icon={<RefreshCw className="h-3 w-3" />}
        label="Loops"
        used={budget.loops_used}
        max={budget.loops_max}
        compact
      />
      <BudgetBar
        icon={<Coins className="h-3 w-3" />}
        label="Tokens"
        used={budget.tokens_used}
        max={budget.tokens_max}
        format={formatTokens}
        compact
      />
      <BudgetBar
        icon={<Clock className="h-3 w-3" />}
        label="Time"
        used={budget.wall_time_ms}
        max={budget.wall_time_max_ms}
        format={formatTime}
        compact
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Full mode (standalone panel or overlay)
// ---------------------------------------------------------------------------

export function BudgetMonitor() {
  const budget = useWorkflowStore((s) => s.budget);
  const runStatus = useWorkflowStore((s) => s.runStatus);
  const [expanded, setExpanded] = useState(true);

  if (runStatus === 'idle') {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8 text-awp-muted">
        <Coins className="h-8 w-8 opacity-40" />
        <p className="text-xs">Budget tracking appears during execution</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-awp-border bg-awp-panel/60 backdrop-blur-sm overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-awp-text hover:bg-awp-bg/40 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Coins className="h-4 w-4 text-awp-blue" />
          <span>Budget Monitor</span>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-awp-muted" />
        ) : (
          <ChevronDown className="h-4 w-4 text-awp-muted" />
        )}
      </button>

      {expanded && (
        <div className="space-y-3 px-4 pb-4 animate-fade-in">
          <BudgetBar
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            label="Loops"
            used={budget.loops_used}
            max={budget.loops_max}
          />
          <BudgetBar
            icon={<Coins className="h-3.5 w-3.5" />}
            label="Tokens"
            used={budget.tokens_used}
            max={budget.tokens_max}
            format={formatTokens}
          />
          <BudgetBar
            icon={<Clock className="h-3.5 w-3.5" />}
            label="Wall Time"
            used={budget.wall_time_ms}
            max={budget.wall_time_max_ms}
            format={formatTime}
          />
          <BudgetBar
            icon={<Users className="h-3.5 w-3.5" />}
            label="Workers"
            used={budget.workers_used}
            max={budget.workers_max}
          />
          <BudgetBar
            icon={<Wrench className="h-3.5 w-3.5" />}
            label="Tool Calls"
            used={budget.tool_calls_used}
            max={budget.tool_calls_max}
          />
        </div>
      )}
    </div>
  );
}
