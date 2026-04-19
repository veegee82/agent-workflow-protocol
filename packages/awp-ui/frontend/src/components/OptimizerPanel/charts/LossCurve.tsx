import { useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import type { DotProps } from 'recharts';
import type { EpochDetail } from '@/api/client';
import {
  COLORS,
  TOOLTIP_STYLE,
  ChartCard,
  EmptyState,
} from '@/components/MetricsPanel/charts/_shared';

/**
 * Mean-loss-per-epoch line with a 3-epoch moving average overlay.
 *
 * Dot coloring encodes what happened in the epoch:
 * * green → at least one ``update`` event, no rollback
 * * red   → any ``rollback`` event (regression)
 * * grey  → no events (pre-A3 row, or an epoch where the optimizer was
 *           not consulted — e.g. the last epoch or an epoch with no
 *           candidate update)
 *
 * Missing (null) mean_loss values produce a gap in the line — recharts
 * handles `null` naturally when `connectNulls={false}`.
 */
interface Props {
  epochs: EpochDetail[];
}

interface Row {
  epoch_num: number;
  mean_loss: number | null;
  moving_avg: number | null;
  // Visual classification used by the custom Dot renderer.
  variant: 'update' | 'rollback' | 'none';
  events: EpochDetail['events'];
  parent_artifacts: Record<string, number>;
  child_artifacts: Record<string, number>;
}

export function LossCurve({ epochs }: Props) {
  const rows = useMemo<Row[]>(() => {
    const sorted = [...epochs].sort((a, b) => a.epoch_num - b.epoch_num);

    // Compute a 3-epoch centered moving average on mean_loss, skipping
    // nulls. Avoid emitting an MA until we have 3 data points — with
    // <3 points, a "moving average" is just the latest value and would
    // be misleading.
    const maBuf: Array<{ epoch_num: number; value: number }> = [];
    const lossByEpoch = new Map<number, number | null>();
    for (const e of sorted) {
      lossByEpoch.set(e.epoch_num, e.mean_loss);
      if (e.mean_loss != null) {
        maBuf.push({ epoch_num: e.epoch_num, value: e.mean_loss });
      }
    }

    return sorted.map((e): Row => {
      // Moving average: mean of the last up-to-3 non-null losses ending
      // at this epoch. If fewer than 3 valid points exist, we do not
      // emit an MA value for that epoch.
      let ma: number | null = null;
      if (e.mean_loss != null) {
        const window = maBuf.filter(
          (b) => b.epoch_num <= e.epoch_num && b.epoch_num > e.epoch_num - 3,
        );
        if (window.length >= 3) {
          ma = window.reduce((acc, x) => acc + x.value, 0) / window.length;
        }
      }
      const hasRollback = e.events.some((ev) => ev.type === 'rollback');
      const hasUpdate = e.events.some((ev) => ev.type === 'update');
      const variant: 'update' | 'rollback' | 'none' = hasRollback
        ? 'rollback'
        : hasUpdate
          ? 'update'
          : 'none';
      return {
        epoch_num: e.epoch_num,
        mean_loss: e.mean_loss,
        moving_avg: ma,
        variant,
        events: e.events,
        parent_artifacts: e.parent_artifacts,
        child_artifacts: e.child_artifacts,
      };
    });
  }, [epochs]);

  if (!rows.length) {
    return (
      <ChartCard title="Loss Curve">
        <EmptyState label="No epochs yet" />
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Loss Curve"
      subtitle={`${rows.length} epoch${rows.length === 1 ? '' : 's'}`}
    >
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 4 }}>
          <CartesianGrid stroke={COLORS.border} strokeDasharray="3 3" />
          <XAxis
            dataKey="epoch_num"
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
            content={<LossTooltip />}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, color: COLORS.muted }}
            iconSize={10}
          />
          <Line
            type="monotone"
            dataKey="mean_loss"
            name="mean_loss"
            stroke={COLORS.blue}
            strokeWidth={2}
            connectNulls={false}
            dot={<LossDot />}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="moving_avg"
            name="MA(3)"
            stroke={COLORS.muted}
            strokeWidth={1.5}
            strokeDasharray="4 4"
            connectNulls={false}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function LossDot(props: DotProps & { payload?: Row }) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null || !payload) return null;
  // mean_loss null → skip dot entirely (gap in the line).
  if (payload.mean_loss == null) return null;
  const color =
    payload.variant === 'rollback'
      ? COLORS.red
      : payload.variant === 'update'
        ? COLORS.green
        : COLORS.muted;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={4}
      fill={color}
      stroke={COLORS.panel}
      strokeWidth={1}
    />
  );
}

interface TooltipPayloadItem {
  payload?: Row;
  value?: number;
}

function LossTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;

  const updateEv = row.events.find((e) => e.type === 'update');
  const rollbackEv = row.events.find((e) => e.type === 'rollback');
  const primary = rollbackEv ?? updateEv;

  return (
    <div
      style={{
        ...TOOLTIP_STYLE,
        padding: '8px 10px',
        minWidth: 200,
      }}
    >
      <div style={{ color: COLORS.text, fontWeight: 500, marginBottom: 4 }}>
        Epoch {row.epoch_num}
      </div>
      <div style={{ color: COLORS.muted, marginBottom: 2 }}>
        mean_loss:{' '}
        <span style={{ color: COLORS.blue, fontFamily: 'monospace' }}>
          {row.mean_loss == null ? 'n/a' : row.mean_loss.toFixed(3)}
        </span>
      </div>
      {row.moving_avg != null && (
        <div style={{ color: COLORS.muted, marginBottom: 2 }}>
          MA(3):{' '}
          <span style={{ fontFamily: 'monospace' }}>
            {row.moving_avg.toFixed(3)}
          </span>
        </div>
      )}
      {primary && (
        <div style={{ color: COLORS.muted, marginTop: 4 }}>
          {primary.type === 'rollback' ? (
            <span style={{ color: COLORS.red }}>rollback</span>
          ) : (
            <span style={{ color: COLORS.green }}>update</span>
          )}
          : {primary.artifact}{' '}
          <span style={{ fontFamily: 'monospace' }}>
            v{primary.from_version}→v{primary.to_version}
          </span>
        </div>
      )}
      {!primary && (
        <div style={{ color: COLORS.muted, marginTop: 4, fontStyle: 'italic' }}>
          no artifact events
        </div>
      )}
    </div>
  );
}

export default LossCurve;
