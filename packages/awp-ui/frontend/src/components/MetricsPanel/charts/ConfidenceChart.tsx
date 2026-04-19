import { useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, SERIES_PALETTE, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// Mean confidence over iterations, with faint per-worker overlay lines so the
// user can see spread.
export function ConfidenceChart() {
  const data = useWorkflowStore((s) => s.metrics.confidence);

  const { chartData, workerNames } = useMemo(() => {
    const names = new Set<string>();
    const rows = data.map((e) => {
      const row: Record<string, number | string> = {
        iteration: e.iteration,
        mean: e.mean,
      };
      (e.per_worker ?? []).forEach((w) => {
        names.add(w.name);
        row[w.name] = w.confidence;
      });
      return row;
    });
    return { chartData: rows, workerNames: Array.from(names) };
  }, [data]);

  if (!chartData.length) {
    return (
      <ChartCard title="Confidence">
        <EmptyState label="No confidence metrics yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Confidence" subtitle={`${chartData.length} iter`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            dataKey="iteration"
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          {workerNames.map((name, i) => (
            <Line
              key={name}
              type="monotone"
              dataKey={name}
              stroke={SERIES_PALETTE[(i + 1) % SERIES_PALETTE.length]}
              strokeOpacity={0.3}
              strokeWidth={1}
              dot={false}
              isAnimationActive={false}
            />
          ))}
          <Line
            type="monotone"
            dataKey="mean"
            stroke={COLORS.purple}
            strokeWidth={2}
            dot={{ fill: COLORS.purple, r: 3 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default ConfidenceChart;
