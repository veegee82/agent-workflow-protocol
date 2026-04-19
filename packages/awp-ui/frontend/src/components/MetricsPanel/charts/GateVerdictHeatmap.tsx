import { useMemo } from 'react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { COLORS, ChartCard, EmptyState } from './_shared';

// Plain CSS-grid heatmap: one row per unique gate, one column per iteration.
// Cell colors:
//   green  = pass
//   red    = rejected
//   grey   = gate did not fire this iteration
// A tooltip with the most-recent reason is attached via the native title attr
// so we avoid pulling in recharts for a non-chart visual.
export function GateVerdictHeatmap() {
  const events = useWorkflowStore((s) => s.metrics.gate_events);

  const { gates, iterations, cells } = useMemo(() => {
    const gatesSet = new Set<string>();
    const iterSet = new Set<number>();
    // cells[gate][iteration] = latest entry for that cell (deterministic: the
    // last event wins, mirroring how the runtime logs gate outcomes).
    const byCell = new Map<string, { verdict: string; reason: string }>();
    for (const e of events) {
      if (e.iteration == null || !Number.isFinite(e.iteration) || e.iteration < 0) continue;
      gatesSet.add(e.gate);
      iterSet.add(e.iteration);
      byCell.set(`${e.gate}::${e.iteration}`, { verdict: e.verdict, reason: e.reason });
    }
    return {
      gates: Array.from(gatesSet).sort(),
      iterations: Array.from(iterSet).sort((a, b) => a - b),
      cells: byCell,
    };
  }, [events]);

  if (!gates.length || !iterations.length) {
    return (
      <ChartCard title="Gate verdicts">
        <EmptyState label="No gate events yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Gate verdicts"
      subtitle={`${gates.length} gates x ${iterations.length} iter`}
    >
      <div className="overflow-auto h-full">
        <div
          className="grid gap-[2px] text-[10px]"
          style={{
            gridTemplateColumns: `minmax(120px, max-content) repeat(${iterations.length}, 16px)`,
          }}
        >
          {/* header row: blank + iteration numbers */}
          <div className="sticky left-0 bg-awp-bg z-10" />
          {iterations.map((it) => (
            <div
              key={`h-${it}`}
              className="text-awp-muted text-center"
              title={`iteration ${it}`}
            >
              {it}
            </div>
          ))}
          {/* one row per gate */}
          {gates.map((gate) => (
            <GateRow key={gate} gate={gate} iterations={iterations} cells={cells} />
          ))}
        </div>
        <div className="flex gap-3 mt-2 text-[10px] text-awp-muted/70">
          <LegendDot color={COLORS.green} label="pass" />
          <LegendDot color={COLORS.red} label="rejected" />
          <LegendDot color={COLORS.border} label="not run" />
        </div>
      </div>
    </ChartCard>
  );
}

function GateRow(props: {
  gate: string;
  iterations: number[];
  cells: Map<string, { verdict: string; reason: string }>;
}) {
  return (
    <>
      <div
        className="sticky left-0 bg-awp-bg text-awp-text pr-2 py-0.5 truncate"
        title={props.gate}
      >
        {props.gate}
      </div>
      {props.iterations.map((it) => {
        const cell = props.cells.get(`${props.gate}::${it}`);
        let color: string = COLORS.border;
        if (cell?.verdict === 'passed') color = COLORS.green;
        else if (cell?.verdict === 'rejected') color = COLORS.red;
        const tip = cell
          ? `${props.gate} @ iter ${it}: ${cell.verdict}${cell.reason ? ' — ' + cell.reason : ''}`
          : `${props.gate} @ iter ${it}: not run`;
        return (
          <div
            key={`${props.gate}-${it}`}
            title={tip}
            className="h-4 w-4 rounded-sm"
            style={{ backgroundColor: color, opacity: cell ? 0.85 : 0.35 }}
          />
        );
      })}
    </>
  );
}

function LegendDot(props: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span
        className="inline-block h-2 w-2 rounded-sm"
        style={{ backgroundColor: props.color }}
      />
      {props.label}
    </span>
  );
}

export default GateVerdictHeatmap;
