import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// Cumulative stacked area:
//   completed  = running total of distinct workers reported by metric.confidence
//                (workers that reached a confidence verdict)
//   spawned    = running total of workers_used reported by metric.budget,
//                minus completed (clamped to >=0). Captures workers that were
//                spawned but did not resolve with a confidence payload yet
//                (repair / in-flight / rejected before a confidence result).
// workers_used in the budget payload is already cumulative — we use it as-is
// and derive 'completed' by summing confidence per_worker counts over iters.
export function WorkersPerIterationChart() {
  const budgets = useWorkflowStore((s) => s.metrics.budget);
  const confidences = useWorkflowStore((s) => s.metrics.confidence);

  const chartData = useMemo(() => {
    const completedByIter = new Map<number, number>();
    for (const c of confidences) {
      const n = (c.per_worker ?? []).length;
      completedByIter.set(c.iteration, (completedByIter.get(c.iteration) ?? 0) + n);
    }
    let cumulativeCompleted = 0;
    return budgets.map((b) => {
      cumulativeCompleted += completedByIter.get(b.iteration) ?? 0;
      const total = Math.max(b.workers_used, cumulativeCompleted);
      const completed = Math.min(cumulativeCompleted, total);
      const other = Math.max(0, total - completed);
      return {
        iteration: b.iteration,
        completed,
        other,
      };
    });
  }, [budgets, confidences]);

  const hasAny = chartData.some((r) => r.completed + r.other > 0);
  if (!chartData.length || !hasAny) {
    return (
      <ChartCard title="Workers (cumulative)">
        <EmptyState label="No worker activity yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Workers (cumulative)" subtitle="stacked">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            dataKey="iteration"
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
            width={32}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 10, color: COLORS.muted }} />
          <Area
            type="monotone"
            dataKey="completed"
            name="completed"
            stackId="w"
            stroke={COLORS.green}
            fill={COLORS.green}
            fillOpacity={0.7}
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="other"
            name="spawned"
            stackId="w"
            stroke={COLORS.yellow}
            fill={COLORS.yellow}
            fillOpacity={0.55}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default WorkersPerIterationChart;
