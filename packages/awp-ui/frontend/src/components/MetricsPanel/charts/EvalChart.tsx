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
  ReferenceLine,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// Scalar eval score line with a dashed threshold reference. The per-metric
// breakdown lives in its own chart (EvalPerMetricChart) so each widget has
// exactly one job.
const EVAL_THRESHOLD = 0.7;

export function EvalChart() {
  const data = useWorkflowStore((s) => s.metrics.eval);

  const chartData = useMemo(
    () =>
      data.map((e) => ({
        iteration: e.iteration,
        score: e.score,
      })),
    [data],
  );

  if (!chartData.length) {
    return (
      <ChartCard title="Eval (score)">
        <EmptyState label="No eval metrics yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Eval (score)" subtitle={`${chartData.length} events`}>
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
          <ReferenceLine
            y={EVAL_THRESHOLD}
            stroke={COLORS.yellow}
            strokeDasharray="4 4"
            strokeOpacity={0.6}
            label={{
              value: `thr ${EVAL_THRESHOLD}`,
              fill: COLORS.yellow,
              fontSize: 9,
              position: 'insideTopRight',
            }}
          />
          <Line
            type="monotone"
            dataKey="score"
            name="score"
            stroke={COLORS.cyan}
            strokeWidth={2}
            dot={{ fill: COLORS.cyan, r: 3 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default EvalChart;
