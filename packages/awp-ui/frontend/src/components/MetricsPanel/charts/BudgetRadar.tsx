import { useMemo } from 'react';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// 6-axis radar normalised to [0,1] (used/max). Latest snapshot only.
export function BudgetRadar() {
  const budgetSnaps = useWorkflowStore((s) => s.metrics.budget);
  const toolCalls = useWorkflowStore((s) => s.metrics.tool_calls);

  const radarData = useMemo(() => {
    const latest = budgetSnaps[budgetSnaps.length - 1];
    if (!latest) return [];
    const safe = (u: number, m: number) => {
      if (!m || m <= 0) return 0;
      return Math.max(0, Math.min(1, u / m));
    };
    const toolCallsUsed = latest.tool_calls_used ?? toolCalls.length;
    const maxToolCalls = latest.max_tool_calls ?? Math.max(1, toolCallsUsed);
    return [
      { axis: 'tokens', value: safe(latest.tokens_used, latest.max_tokens ?? 0) },
      { axis: 'loops', value: safe(latest.loops_used, latest.max_loops ?? 0) },
      { axis: 'workers', value: safe(latest.workers_used, latest.max_workers ?? 0) },
      {
        axis: 'wall_time',
        value: safe(latest.wall_time_s, latest.max_wall_time_s ?? 0),
      },
      { axis: 'tool_calls', value: safe(toolCallsUsed, maxToolCalls) },
      {
        axis: 'iterations',
        value: safe(latest.iteration, latest.max_loops ?? 0),
      },
    ];
  }, [budgetSnaps, toolCalls]);

  if (!radarData.length) {
    return (
      <ChartCard title="Budget">
        <EmptyState label="No budget metrics yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Budget" subtitle="latest snapshot">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={radarData} outerRadius="75%">
          <PolarGrid stroke={COLORS.border} />
          <PolarAngleAxis dataKey="axis" tick={{ fill: COLORS.muted, fontSize: 10 }} />
          <PolarRadiusAxis
            angle={30}
            domain={[0, 1]}
            tick={{ fill: COLORS.muted, fontSize: 9 }}
            stroke={COLORS.border}
          />
          <Radar
            name="used/max"
            dataKey="value"
            stroke={COLORS.yellow}
            fill={COLORS.yellow}
            fillOpacity={0.25}
            isAnimationActive={false}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
        </RadarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default BudgetRadar;
