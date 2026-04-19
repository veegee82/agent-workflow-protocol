import { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// Horizontal bar of top-10 most-called tools. The tool_name bar is primary;
// success rate is shown as a thinner secondary bar on the same row (0..calls).
export function ToolCallFrequencyChart() {
  const calls = useWorkflowStore((s) => s.metrics.tool_calls);

  const chartData = useMemo(() => {
    type Agg = { calls: number; ok: number };
    const byTool = new Map<string, Agg>();
    for (const c of calls) {
      const name = c.tool_name || '(unknown)';
      const cur = byTool.get(name) ?? { calls: 0, ok: 0 };
      cur.calls += 1;
      if (c.success) cur.ok += 1;
      byTool.set(name, cur);
    }
    return Array.from(byTool.entries())
      .map(([name, a]) => ({
        name,
        calls: a.calls,
        // Success shown as an absolute count (a fraction of calls) so both
        // bars share a single x-axis without confusing a second percentage
        // scale. The tooltip exposes the raw success count.
        success: a.ok,
        success_rate: a.calls ? a.ok / a.calls : 0,
      }))
      .sort((a, b) => b.calls - a.calls)
      .slice(0, 10);
  }, [calls]);

  if (!chartData.length) {
    return (
      <ChartCard title="Tool calls">
        <EmptyState label="No tool calls yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Tool calls" subtitle={`top ${chartData.length}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 4, right: 8, bottom: 4, left: 4 }}
        >
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            type="number"
            allowDecimals={false}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={140}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(value, key, ctx) => {
              const num = typeof value === 'number' ? value : Number(value ?? 0);
              if (key === 'success') {
                const payload = (ctx as { payload?: { success_rate?: number } } | undefined)
                  ?.payload;
                const rate = (payload?.success_rate ?? 0) * 100;
                return [`${num} (${rate.toFixed(0)}%)`, 'successes'];
              }
              return [String(value ?? ''), String(key ?? '')];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: COLORS.muted }} />
          <Bar
            dataKey="calls"
            name="calls"
            fill={COLORS.purple}
            fillOpacity={0.35}
            barSize={10}
            isAnimationActive={false}
          >
            {chartData.map((_, i) => (
              <Cell key={i} fill={COLORS.purple} fillOpacity={0.35} />
            ))}
          </Bar>
          <Bar
            dataKey="success"
            name="successes"
            fill={COLORS.green}
            fillOpacity={0.85}
            barSize={6}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default ToolCallFrequencyChart;
