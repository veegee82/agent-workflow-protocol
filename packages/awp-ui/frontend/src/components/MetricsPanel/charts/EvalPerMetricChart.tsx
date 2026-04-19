import { useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, SERIES_PALETTE, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// One line per key in metric_scores. The scalar eval score lives in EvalChart;
// this widget is intentionally only about the breakdown.
export function EvalPerMetricChart() {
  const data = useWorkflowStore((s) => s.metrics.eval);

  const { chartData, metricNames } = useMemo(() => {
    const names = new Set<string>();
    const rows = data.map((e) => {
      const row: Record<string, number | string> = { iteration: e.iteration };
      Object.entries(e.metric_scores ?? {}).forEach(([k, v]) => {
        names.add(k);
        row[k] = v;
      });
      return row;
    });
    return { chartData: rows, metricNames: Array.from(names) };
  }, [data]);

  if (!chartData.length || !metricNames.length) {
    return (
      <ChartCard title="Eval per metric">
        <EmptyState label="No per-metric eval scores yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Eval per metric"
      subtitle={`${metricNames.length} metric${metricNames.length === 1 ? '' : 's'}`}
    >
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
          <Legend wrapperStyle={{ fontSize: 10, color: COLORS.muted }} />
          {metricNames.map((name, i) => (
            <Line
              key={name}
              type="monotone"
              dataKey={name}
              name={name}
              stroke={SERIES_PALETTE[i % SERIES_PALETTE.length]}
              strokeWidth={1.5}
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default EvalPerMetricChart;
