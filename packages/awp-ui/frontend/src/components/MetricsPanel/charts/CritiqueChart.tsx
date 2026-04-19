import { useMemo } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// Per-iteration critique score on the left axis (scores are not cumulative);
// cumulative defect count on the right axis — running total of all defects
// reported by the critique engine over the run, so the growing bar height
// directly visualizes accumulating defect burden.
export function CritiqueChart() {
  const data = useWorkflowStore((s) => s.metrics.critique);

  const chartData = useMemo(() => {
    let cumDefects = 0;
    return data.map((e) => {
      cumDefects += e.defect_count ?? 0;
      return {
        iteration: e.iteration,
        score: e.score,
        defects_cumulative: cumDefects,
      };
    });
  }, [data]);

  if (!chartData.length) {
    return (
      <ChartCard title="Critique">
        <EmptyState label="No critique metrics yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Critique" subtitle={`${chartData.length} iter`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            dataKey="iteration"
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            yAxisId="left"
            domain={[0, 1]}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            allowDecimals={false}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 10, color: COLORS.muted }} />
          <Bar
            yAxisId="right"
            dataKey="defects_cumulative"
            name="defects (cumulative)"
            fill={COLORS.orange}
            fillOpacity={0.55}
            isAnimationActive={false}
          />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="score"
            name="score"
            stroke={COLORS.green}
            strokeWidth={2}
            dot={{ fill: COLORS.green, r: 3 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default CritiqueChart;
