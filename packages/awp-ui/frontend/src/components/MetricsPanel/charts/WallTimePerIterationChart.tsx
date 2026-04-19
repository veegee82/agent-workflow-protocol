import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// wall_time_s in the budget payload is already cumulative — plot it directly
// as a monotonically non-decreasing area chart so viewers see total wall-clock
// consumed over the run rather than per-iteration deltas.
export function WallTimePerIterationChart() {
  const data = useWorkflowStore((s) => s.metrics.budget);

  const chartData = useMemo(
    () =>
      data.map((e) => ({
        iteration: e.iteration,
        wall_time_s: Number(e.wall_time_s.toFixed(2)),
      })),
    [data],
  );

  if (!chartData.length) {
    return (
      <ChartCard title="Wall time (cumulative)">
        <EmptyState label="No budget metrics yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Wall time (cumulative)" subtitle="seconds">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            dataKey="iteration"
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
            width={40}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Area
            type="monotone"
            dataKey="wall_time_s"
            name="seconds"
            stroke={COLORS.blue}
            fill={COLORS.blue}
            fillOpacity={0.3}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default WallTimePerIterationChart;
