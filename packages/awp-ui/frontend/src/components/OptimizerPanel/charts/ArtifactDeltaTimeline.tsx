import { useMemo, useState } from 'react';
import type { EpochDetail, ArtifactEvent } from '@/api/client';
import {
  COLORS,
  ChartCard,
  EmptyState,
} from '@/components/MetricsPanel/charts/_shared';

/**
 * One row per artifact name, one column per epoch. A circle marks an
 * update, an "X" marks a rollback.
 *
 * Implemented as custom SVG to keep full control over the marker shape,
 * the click target, and the hover tooltip — recharts Scatter doesn't
 * support heterogeneous point shapes without a cumbersome shape prop.
 *
 * Interaction: clicking a marker opens a diff drawer for (from_version →
 * to_version) of that artifact. The parent (OptimizerPanel) owns the
 * drawer state and receives marker events via ``onMarkerClick``.
 */
interface Props {
  epochs: EpochDetail[];
  onMarkerClick: (ev: {
    artifact: string;
    from_version: number;
    to_version: number;
    type: 'update' | 'rollback';
  }) => void;
}

// Canonical artifact-name order. Matches DEFAULTS in
// packages/awp-runtime/src/awp/outer_loop/defaults/__init__.py —
// any new artifact added to the runtime defaults dict must be mirrored
// here too (see docs/outer-loop.md for the list).
const ARTIFACT_ORDER = [
  'worker_pitfalls',
  'manager_planning_preamble',
  'experiment_context_hint_template',
  'pattern_library',
  'tool_description_templates',
  'critique_rubric',
] as const;

const ROW_HEIGHT = 34;
const MARGIN_TOP = 28;
const MARGIN_LEFT = 190;
const MARGIN_RIGHT = 16;
const MARGIN_BOTTOM = 22;

export function ArtifactDeltaTimeline({ epochs, onMarkerClick }: Props) {
  const { epochNums, events } = useMemo(() => {
    const nums = Array.from(
      new Set(epochs.map((e) => e.epoch_num)),
    ).sort((a, b) => a - b);
    // Flatten events, tagged with their epoch_num.
    const flat: Array<{ epoch_num: number; event: ArtifactEvent }> = [];
    for (const ep of epochs) {
      for (const ev of ep.events) {
        flat.push({ epoch_num: ep.epoch_num, event: ev });
      }
    }
    return { epochNums: nums, events: flat };
  }, [epochs]);

  if (!epochs.length) {
    return (
      <ChartCard title="Artifact Deltas">
        <EmptyState label="No epochs yet" />
      </ChartCard>
    );
  }

  // Layout: fixed-height rows, x-axis stretches to ResponsiveContainer.
  const rows = ARTIFACT_ORDER.length;
  const height = MARGIN_TOP + rows * ROW_HEIGHT + MARGIN_BOTTOM;

  return (
    <ChartCard
      title="Artifact Deltas"
      subtitle={`${epochNums.length} epoch${epochNums.length === 1 ? '' : 's'}`}
    >
      <div className="w-full overflow-x-auto">
        <TimelineSvg
          epochNums={epochNums}
          events={events}
          height={height}
          onMarkerClick={onMarkerClick}
        />
      </div>
    </ChartCard>
  );
}

function TimelineSvg({
  epochNums,
  events,
  height,
  onMarkerClick,
}: {
  epochNums: number[];
  events: Array<{ epoch_num: number; event: ArtifactEvent }>;
  height: number;
  onMarkerClick: Props['onMarkerClick'];
}) {
  // Width scales with epoch count; use at least 360 px of plotting area
  // so a 1-epoch suite doesn't look broken.
  const plotWidth = Math.max(360, epochNums.length * 70);
  const width = MARGIN_LEFT + plotWidth + MARGIN_RIGHT;
  const xScale = (epoch: number): number => {
    if (epochNums.length === 1) {
      return MARGIN_LEFT + plotWidth / 2;
    }
    const min = epochNums[0];
    const max = epochNums[epochNums.length - 1];
    return (
      MARGIN_LEFT +
      ((epoch - min) / Math.max(1, max - min)) * plotWidth
    );
  };
  const yForArtifact = (name: string): number => {
    const idx = ARTIFACT_ORDER.indexOf(name as typeof ARTIFACT_ORDER[number]);
    return MARGIN_TOP + (idx < 0 ? 0 : idx) * ROW_HEIGHT + ROW_HEIGHT / 2;
  };

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label="Artifact delta timeline"
    >
      {/* Row dividers and labels */}
      {ARTIFACT_ORDER.map((name, idx) => {
        const y = MARGIN_TOP + idx * ROW_HEIGHT;
        return (
          <g key={name}>
            <line
              x1={MARGIN_LEFT}
              x2={width - MARGIN_RIGHT}
              y1={y + ROW_HEIGHT / 2}
              y2={y + ROW_HEIGHT / 2}
              stroke={COLORS.border}
              strokeOpacity={0.3}
            />
            <text
              x={MARGIN_LEFT - 8}
              y={y + ROW_HEIGHT / 2 + 4}
              fontSize={10}
              fill={COLORS.muted}
              textAnchor="end"
            >
              {name}
            </text>
          </g>
        );
      })}
      {/* X-axis: epoch numbers */}
      {epochNums.map((n) => (
        <g key={n}>
          <text
            x={xScale(n)}
            y={MARGIN_TOP - 10}
            fontSize={10}
            fill={COLORS.muted}
            textAnchor="middle"
          >
            e{n}
          </text>
          <line
            x1={xScale(n)}
            x2={xScale(n)}
            y1={MARGIN_TOP}
            y2={height - MARGIN_BOTTOM}
            stroke={COLORS.border}
            strokeOpacity={0.15}
          />
        </g>
      ))}
      {/* Markers */}
      {events.map(({ epoch_num, event }, i) => (
        <Marker
          key={`${epoch_num}-${event.artifact}-${event.from_version}-${event.to_version}-${i}`}
          x={xScale(epoch_num)}
          y={yForArtifact(event.artifact)}
          type={event.type}
          event={event}
          epochNum={epoch_num}
          onClick={() =>
            onMarkerClick({
              artifact: event.artifact,
              from_version: event.from_version,
              to_version: event.to_version,
              type: event.type,
            })
          }
        />
      ))}
    </svg>
  );
}

function Marker({
  x,
  y,
  type,
  event,
  epochNum,
  onClick,
}: {
  x: number;
  y: number;
  type: 'update' | 'rollback';
  event: ArtifactEvent;
  epochNum: number;
  onClick: () => void;
}) {
  const [hover, setHover] = useState(false);
  const color = type === 'rollback' ? COLORS.red : COLORS.green;
  const onMouseEnter = () => setHover(true);
  const onMouseLeave = () => setHover(false);
  return (
    <g
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onClick={onClick}
      style={{ cursor: 'pointer' }}
    >
      {type === 'rollback' ? (
        <g transform={`translate(${x}, ${y})`}>
          <line
            x1={-5}
            y1={-5}
            x2={5}
            y2={5}
            stroke={color}
            strokeWidth={2.25}
            strokeLinecap="round"
          />
          <line
            x1={-5}
            y1={5}
            x2={5}
            y2={-5}
            stroke={color}
            strokeWidth={2.25}
            strokeLinecap="round"
          />
          {/* invisible hit target to widen the click area */}
          <circle cx={0} cy={0} r={9} fill="transparent" />
        </g>
      ) : (
        <circle
          cx={x}
          cy={y}
          r={5}
          fill={color}
          stroke={COLORS.panel}
          strokeWidth={1}
        />
      )}
      {hover && (
        <foreignObject x={x + 10} y={y - 40} width={220} height={90}>
          <div
            style={{
              backgroundColor: COLORS.panel,
              border: `1px solid ${COLORS.border}`,
              borderRadius: 6,
              color: COLORS.text,
              fontSize: 10,
              padding: '6px 8px',
              fontFamily:
                'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont',
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 2 }}>
              {type === 'rollback' ? 'Rollback' : 'Update'} @ e{epochNum}
            </div>
            <div style={{ color: COLORS.muted, marginBottom: 2 }}>
              {event.artifact}{' '}
              <span style={{ fontFamily: 'monospace', color: COLORS.text }}>
                v{event.from_version}→v{event.to_version}
              </span>
            </div>
            <div style={{ color: COLORS.muted, fontSize: 10 }}>
              (click for diff)
            </div>
          </div>
        </foreignObject>
      )}
    </g>
  );
}

export default ArtifactDeltaTimeline;
