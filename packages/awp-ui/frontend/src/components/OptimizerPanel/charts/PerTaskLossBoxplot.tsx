import { useMemo } from 'react';
import {
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ErrorBar,
  Scatter,
  Legend,
} from 'recharts';
import type { EpochDetail, EpochTaskLoss } from '@/api/client';
import {
  COLORS,
  TOOLTIP_STYLE,
  ChartCard,
  EmptyState,
} from '@/components/MetricsPanel/charts/_shared';

/**
 * Per-epoch boxplot-ish rendering: min/max as a vertical error bar, the
 * median as the central dot.
 *
 * Recharts has no native boxplot, so we use the
 * ``Scatter + ErrorBar`` pattern: Scatter places a point at the median
 * and ErrorBar draws an asymmetric error bar from (median - lo) to
 * (median + hi) to reach min and max respectively.
 *
 * Null losses are skipped — the aggregate only reflects tasks that
 * produced a loss. Epochs with zero non-null tasks are rendered as an
 * empty column (no dot, no bar).
 */
interface Props {
  epochs: EpochDetail[];
}

interface Row {
  epoch_num: number;
  median: number | null;
  // ErrorBar expects a [low, high] pair where low/high are deltas from
  // the center value. We pre-compute them so recharts places the error
  // bar at (median - low, median + high).
  range: [number, number] | null;
  min: number | null;
  max: number | null;
  count: number;
  tasks: EpochTaskLoss[];
}

function computeStats(losses: number[]): {
  median: number;
  min: number;
  max: number;
} {
  const sorted = [...losses].sort((a, b) => a - b);
  const n = sorted.length;
  const min = sorted[0];
  const max = sorted[n - 1];
  let median: number;
  if (n % 2 === 1) {
    median = sorted[(n - 1) / 2];
  } else {
    median = (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  }
  return { median, min, max };
}

export function PerTaskLossBoxplot({ epochs }: Props) {
  const rows = useMemo<Row[]>(() => {
    const sorted = [...epochs].sort((a, b) => a.epoch_num - b.epoch_num);
    return sorted.map((e): Row => {
      const valid = e.per_task_losses.filter(
        (t): t is EpochTaskLoss & { loss: number } => t.loss != null,
      );
      if (valid.length === 0) {
        return {
          epoch_num: e.epoch_num,
          median: null,
          range: null,
          min: null,
          max: null,
          count: 0,
          tasks: e.per_task_losses,
        };
      }
      const { median, min, max } = computeStats(valid.map((t) => t.loss));
      return {
        epoch_num: e.epoch_num,
        median,
        range: [median - min, max - median],
        min,
        max,
        count: valid.length,
        tasks: e.per_task_losses,
      };
    });
  }, [epochs]);

  if (!rows.length) {
    return (
      <ChartCard title="Per-Task Loss Distribution">
        <EmptyState label="No epochs yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Per-Task Loss Distribution"
      subtitle="min/median/max per epoch"
    >
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart
          data={rows}
          margin={{ top: 8, right: 16, bottom: 8, left: 4 }}
        >
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            dataKey="epoch_num"
            type="number"
            domain={['dataMin', 'dataMax']}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
            label={{
              value: 'epoch',
              position: 'insideBottom',
              offset: -2,
              fill: COLORS.muted,
              fontSize: 10,
            }}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: COLORS.muted, fontSize: 10 }}
            stroke={COLORS.border}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            content={<BoxplotTooltip />}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, color: COLORS.muted }}
            iconSize={10}
          />
          <Scatter
            name="median (bar = min-max)"
            dataKey="median"
            fill={COLORS.yellow}
            line={false}
            isAnimationActive={false}
          >
            <ErrorBar
              dataKey="range"
              width={6}
              strokeWidth={2}
              stroke={COLORS.purple}
              direction="y"
            />
          </Scatter>
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

interface TooltipPayloadItem {
  payload?: Row;
}

function BoxplotTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div style={{ ...TOOLTIP_STYLE, padding: '8px 10px', minWidth: 220 }}>
      <div style={{ color: COLORS.text, fontWeight: 500, marginBottom: 4 }}>
        Epoch {row.epoch_num}
      </div>
      {row.median == null ? (
        <div style={{ color: COLORS.muted, fontStyle: 'italic' }}>
          No per-task losses recorded
        </div>
      ) : (
        <>
          <div style={{ color: COLORS.muted, marginBottom: 2 }}>
            min:{' '}
            <span style={{ fontFamily: 'monospace', color: COLORS.text }}>
              {row.min?.toFixed(3)}
            </span>
            {'  '}median:{' '}
            <span style={{ fontFamily: 'monospace', color: COLORS.yellow }}>
              {row.median.toFixed(3)}
            </span>
            {'  '}max:{' '}
            <span style={{ fontFamily: 'monospace', color: COLORS.text }}>
              {row.max?.toFixed(3)}
            </span>
          </div>
          <div
            style={{
              color: COLORS.muted,
              marginTop: 4,
              borderTop: `1px solid ${COLORS.border}`,
              paddingTop: 4,
            }}
          >
            {row.tasks.slice(0, 8).map((t) => (
              <div key={t.run_id} style={{ fontSize: 10 }}>
                {t.task_name}:{' '}
                <span style={{ fontFamily: 'monospace', color: COLORS.text }}>
                  {t.loss == null ? 'n/a' : t.loss.toFixed(3)}
                </span>
              </div>
            ))}
            {row.tasks.length > 8 && (
              <div style={{ fontSize: 10, fontStyle: 'italic' }}>
                ... +{row.tasks.length - 8} more
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default PerTaskLossBoxplot;
