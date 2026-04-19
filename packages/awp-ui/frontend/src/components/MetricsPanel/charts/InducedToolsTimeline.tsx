import { useMemo } from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ZAxis,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// A marker on an iteration axis every time a *new* induced tool appears in the
// tool-call stream. The runtime names induced tools ``dynamic.induced_<hash>``
// (see tool_inducer.py); the first-seen iteration for each fqn is the moment
// the ToolInducer promoted it to a persistent dynamic tool.
export function InducedToolsTimeline() {
  const calls = useWorkflowStore((s) => s.metrics.tool_calls);
  const budgets = useWorkflowStore((s) => s.metrics.budget);

  const { markers, maxIter } = useMemo(() => {
    const firstSeen = new Map<string, number>();
    for (const c of calls) {
      if (!c.tool_name.startsWith('dynamic.induced_')) continue;
      if (!firstSeen.has(c.tool_name)) {
        firstSeen.set(c.tool_name, c.iteration >= 0 ? c.iteration : 0);
      }
    }
    const points = Array.from(firstSeen.entries()).map(([name, iter]) => ({
      name,
      iteration: iter,
      y: 1,
    }));
    const callsMax = calls.reduce((m, c) => Math.max(m, c.iteration), 0);
    const budgetMax = budgets.reduce((m, b) => Math.max(m, b.iteration), 0);
    return { markers: points, maxIter: Math.max(callsMax, budgetMax, 1) };
  }, [calls, budgets]);

  if (!markers.length) {
    return (
      <ChartCard title="Induced tools timeline" subtitle="β induction">
        <EmptyState label="No induced tools yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Induced tools timeline" subtitle={`${markers.length} tool(s)`}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 4, right: 12, bottom: 4, left: 12 }}>
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="iteration"
            domain={[0, maxIter]}
            allowDecimals={false}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[0, 2]}
            tick={false}
            axisLine={false}
            width={4}
          />
          <ZAxis type="number" range={[80, 80]} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            cursor={{ strokeDasharray: '3 3', stroke: COLORS.border }}
            formatter={(value, key) => {
              if (key === 'iteration') return [String(value ?? ''), 'first seen @ iter'];
              if (key === 'y') return ['', ''];
              return [String(value ?? ''), String(key ?? '')];
            }}
            labelFormatter={() => ''}
          />
          <Scatter
            data={markers}
            fill={COLORS.cyan}
            shape="diamond"
            isAnimationActive={false}
          />
        </ScatterChart>
      </ResponsiveContainer>
      <div className="mt-1 text-[10px] text-awp-muted/70 font-mono truncate">
        {markers.map((m) => m.name).join('  ·  ')}
      </div>
    </ChartCard>
  );
}

export default InducedToolsTimeline;
