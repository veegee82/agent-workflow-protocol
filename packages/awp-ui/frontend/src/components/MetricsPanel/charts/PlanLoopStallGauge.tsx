import { useMemo } from 'react';
import {
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
  ResponsiveContainer,
} from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, ChartCard, EmptyState } from './_shared';

// Derived stall counter: the trailing run of consecutive rejections on either
// `plan_loop` gates or any completion-gate chain reject ( deliverable_presence,
// placeholder, file, structural_integrity, critique, eval, deliverable ).
// A successful gate or a new iteration without any completion gate resets it.
// Max-streak gives the scalar ceiling; current-streak drives the gauge.
const COMPLETION_GATES = new Set([
  'deliverable_presence',
  'placeholder',
  'file',
  'structural_integrity',
  'critique',
  'eval',
  'deliverable',
  'plan_loop',
]);

// Shown as a fraction of this implicit ceiling — matches the default
// max_rejected_completions=2 + a small headroom so the gauge does not hit
// 100% the moment we reach the safety-circuit value.
const GAUGE_MAX = 4;

export function PlanLoopStallGauge() {
  const events = useWorkflowStore((s) => s.metrics.gate_events);

  const { current, max, lastReason } = useMemo(() => {
    let cur = 0;
    let best = 0;
    let reason = '';
    for (const e of events) {
      if (!COMPLETION_GATES.has(e.gate)) continue;
      if (e.verdict === 'rejected') {
        cur += 1;
        if (cur > best) best = cur;
        reason = e.reason || reason;
      } else if (e.verdict === 'passed') {
        cur = 0;
      }
    }
    return { current: cur, max: best, lastReason: reason };
  }, [events]);

  if (!events.length) {
    return (
      <ChartCard title="Plan-loop / rejection stall">
        <EmptyState label="No gate events yet" />
      </ChartCard>
    );
  }

  const ratio = Math.min(1, current / GAUGE_MAX);
  const color = current >= 2 ? COLORS.red : current >= 1 ? COLORS.orange : COLORS.green;
  const gaugeData = [{ name: 'stall', value: ratio * 100, fill: color }];

  return (
    <ChartCard
      title="Plan-loop / rejection stall"
      subtitle={`max observed ${max}`}
    >
      <div className="h-full flex items-center">
        <div className="w-1/2 h-full">
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              innerRadius="60%"
              outerRadius="95%"
              startAngle={180}
              endAngle={0}
              data={gaugeData}
            >
              <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
              <RadialBar background dataKey="value" cornerRadius={6} isAnimationActive={false} />
            </RadialBarChart>
          </ResponsiveContainer>
        </div>
        <div className="w-1/2 pl-3 flex flex-col justify-center">
          <div className="text-2xl font-mono text-awp-text leading-none">
            {current}
            <span className="text-awp-muted/60 text-sm"> / {GAUGE_MAX}</span>
          </div>
          <div className="text-[10px] text-awp-muted mt-1">consecutive rejections</div>
          {lastReason ? (
            <div
              className="mt-2 text-[10px] text-awp-muted/80 line-clamp-3"
              title={lastReason}
            >
              {lastReason}
            </div>
          ) : null}
        </div>
      </div>
    </ChartCard>
  );
}

export default PlanLoopStallGauge;
