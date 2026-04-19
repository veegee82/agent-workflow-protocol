import { useMemo } from 'react';
import {
  ComposedChart,
  Area,
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

// Two series: cumulative tokens_used (area) and per-iteration tokens_rate
// (line on a secondary axis). If tokens_rate is missing from the payload we
// derive it as the consecutive delta of tokens_used.
export function TokenBurnRateChart() {
  const data = useWorkflowStore((s) => s.metrics.budget);

  const chartData = useMemo(() => {
    let prev = 0;
    return data.map((e) => {
      const rate = e.tokens_rate > 0 ? e.tokens_rate : Math.max(0, e.tokens_used - prev);
      prev = e.tokens_used;
      return {
        iteration: e.iteration,
        tokens_used: e.tokens_used,
        tokens_rate: rate,
      };
    });
  }, [data]);

  if (!chartData.length) {
    return (
      <ChartCard title="Token burn rate">
        <EmptyState label="No budget metrics yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Token burn rate" subtitle={`${chartData.length} iter`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
          <defs>
            <linearGradient id="tokenBurnFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLORS.orange} stopOpacity={0.55} />
              <stop offset="100%" stopColor={COLORS.orange} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            dataKey="iteration"
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            yAxisId="left"
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
            width={48}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
            width={40}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 10, color: COLORS.muted }} />
          <Area
            yAxisId="left"
            type="monotone"
            dataKey="tokens_used"
            name="cumulative"
            stroke={COLORS.orange}
            fill="url(#tokenBurnFill)"
            strokeWidth={2}
            isAnimationActive={false}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="tokens_rate"
            name="per-iter"
            stroke={COLORS.cyan}
            strokeWidth={1.5}
            dot={{ r: 2, fill: COLORS.cyan }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default TokenBurnRateChart;
