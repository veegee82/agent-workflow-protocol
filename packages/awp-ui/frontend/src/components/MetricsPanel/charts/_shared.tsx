import React from 'react';

// ---------------------------------------------------------------------------
// Shared theme + layout primitives for every chart in the MetricsPanel.
// Keep this file tiny — only colors, tooltip style, and two layout shells.
// AWP theme colors are mirrored from tailwind.config.js; keep them in sync.
// ---------------------------------------------------------------------------

export const COLORS = {
  bg: '#0d1117',
  panel: '#161b22',
  border: '#30363d',
  text: '#c9d1d9',
  muted: '#8b949e',
  blue: '#40C4FF',
  green: '#00E676',
  yellow: '#FFD600',
  orange: '#FF9100',
  red: '#FF1744',
  purple: '#E040FB',
  cyan: '#18FFFF',
} as const;

// Stable palette for per-worker / per-metric / per-category colored series.
export const SERIES_PALETTE = [
  COLORS.purple,
  COLORS.cyan,
  COLORS.green,
  COLORS.yellow,
  COLORS.orange,
  COLORS.blue,
  COLORS.red,
];

export const TOOLTIP_STYLE = {
  backgroundColor: COLORS.panel,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 6,
  color: COLORS.text,
  fontSize: 11,
};

export function ChartCard(props: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={
        'rounded-lg border border-awp-border bg-awp-bg p-3 flex flex-col min-h-[220px] ' +
        (props.className ?? '')
      }
    >
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-xs font-medium text-awp-muted uppercase tracking-wider">
          {props.title}
        </span>
        {props.subtitle ? (
          <span className="text-[10px] text-awp-muted/70">{props.subtitle}</span>
        ) : null}
      </div>
      <div className="flex-1 min-h-[180px]">{props.children}</div>
    </div>
  );
}

export function EmptyState(props: { label: string }) {
  return (
    <div className="h-full flex items-center justify-center text-[11px] text-awp-muted/60">
      {props.label}
    </div>
  );
}
