import { ConfidenceChart } from './charts/ConfidenceChart';
import { CritiqueChart } from './charts/CritiqueChart';
import { EvalChart } from './charts/EvalChart';
import { BudgetRadar } from './charts/BudgetRadar';
import { EvalPerMetricChart } from './charts/EvalPerMetricChart';
import { TokenBurnRateChart } from './charts/TokenBurnRateChart';
import { WallTimePerIterationChart } from './charts/WallTimePerIterationChart';
import { WorkersPerIterationChart } from './charts/WorkersPerIterationChart';
import { GateVerdictHeatmap } from './charts/GateVerdictHeatmap';
import { DefectCategoriesDonut } from './charts/DefectCategoriesDonut';
import { ToolCallFrequencyChart } from './charts/ToolCallFrequencyChart';
import { InducedToolsTimeline } from './charts/InducedToolsTimeline';
import { PlanLoopStallGauge } from './charts/PlanLoopStallGauge';

// ---------------------------------------------------------------------------
// MetricsPanel — thin layout shell for the full B1+B2 chart set. Every chart
// lives in its own file under ./charts/ and reads what it needs directly from
// the workflow store, so adding/removing a widget is a one-line edit here.
// Row layout (stacks to 1 col below md):
//   Row 1: Confidence  | Critique
//   Row 2: Eval        | BudgetRadar
//   Row 3: EvalPerMetr | TokenBurnRate
//   Row 4: WallTime    | WorkersPerIter
//   Row 5: GateHeatmap (full width)
//   Row 6: DefectDonut | ToolCallFreq
//   Row 7: InducedTools (full width)
//   Row 8: StallGauge  (full width, narrow)
// ---------------------------------------------------------------------------

export function MetricsPanel() {
  return (
    <div className="rounded-lg border border-awp-border bg-awp-bg p-3">
      <div className="flex items-baseline justify-between mb-3">
        <span className="text-xs font-medium text-awp-muted uppercase tracking-wider">
          Metrics
        </span>
        <span className="text-[10px] text-awp-muted/70">live</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Row 1 — B1 */}
        <ConfidenceChart />
        <CritiqueChart />

        {/* Row 2 — B1 */}
        <EvalChart />
        <BudgetRadar />

        {/* Row 3 — B2 */}
        <EvalPerMetricChart />
        <TokenBurnRateChart />

        {/* Row 4 — B2 */}
        <WallTimePerIterationChart />
        <WorkersPerIterationChart />

        {/* Row 5 — full width */}
        <div className="md:col-span-2">
          <GateVerdictHeatmap />
        </div>

        {/* Row 6 — B2 */}
        <DefectCategoriesDonut />
        <ToolCallFrequencyChart />

        {/* Row 7 — full width */}
        <div className="md:col-span-2">
          <InducedToolsTimeline />
        </div>

        {/* Row 8 — full width, narrow */}
        <div className="md:col-span-2">
          <PlanLoopStallGauge />
        </div>
      </div>
    </div>
  );
}

export default MetricsPanel;
