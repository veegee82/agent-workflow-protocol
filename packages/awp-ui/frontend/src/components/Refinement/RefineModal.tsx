import { useCallback, useEffect, useState } from 'react';
import { X, Sparkles, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { startRefinement } from '@/api/client';
import { useWorkflowStore } from '@/stores/workflowStore';

/**
 * RefineModal — form for starting a refinement session.
 *
 * Per CLAUDE.md: model fields MUST be free-text `<input>`, never `<select>`.
 * Provider is auto-detected server-side from the model string.
 *
 * Iterations is clamped to [1, 10] — the backend enforces the same with
 * HTTP 422 if the user edits the DOM directly.
 *
 * Tier toggle (spec 2026-04-20 §9.3): optional "Use tiered models across
 * iterations" checkbox swaps the single Manager/Worker inputs for a 3x2
 * grid (low/mid/high x manager/worker), pre-filled from the store's
 * `refinement_tier_*` defaults. The toggle state is per-session only —
 * it is NOT persisted to the workflow store; only the three tier default
 * pairs are persisted (SettingsPanel owns that).
 */
export interface RefineModalProps {
  runId: string;
  seedModel?: string;
  seedWorkerModel?: string;
  onClose: () => void;
  onStarted?: (sessionId: string) => void;
}

const MIN_ITERATIONS = 1;
const MAX_ITERATIONS = 10;

type TierKey = 'refinement_tier_low' | 'refinement_tier_mid' | 'refinement_tier_high';
type TierPair = { manager: string; worker: string };

interface TierRow {
  key: TierKey;
  label: string;
  managerPlaceholder: string;
  workerPlaceholder: string;
}

const TIER_ROWS: TierRow[] = [
  {
    key: 'refinement_tier_low',
    label: 'low',
    managerPlaceholder: 'e.g. deepseek/deepseek-chat-v3.1',
    workerPlaceholder: 'e.g. deepseek/deepseek-chat-v3.1',
  },
  {
    key: 'refinement_tier_mid',
    label: 'mid',
    managerPlaceholder: 'e.g. openai/gpt-5-mini',
    workerPlaceholder: 'e.g. deepseek/deepseek-chat-v3.1',
  },
  {
    key: 'refinement_tier_high',
    label: 'high',
    managerPlaceholder: 'e.g. anthropic/claude-opus-4',
    workerPlaceholder: 'e.g. anthropic/claude-sonnet-4',
  },
];

export function RefineModal({
  runId,
  seedModel,
  seedWorkerModel,
  onClose,
  onStarted,
}: RefineModalProps) {
  // Pre-fill iterations from Settings → Optimizers → Refinement default.
  // Fallback to 3 on undefined so cached stores predating this field
  // still render a sensible default.
  const defaultIterations = useWorkflowStore(
    (s) => s.config.refinement_default_iterations,
  );
  // Persistent tier defaults from the workflow store. Reads are safe
  // because SettingsPanel also initialises them — cached stores that
  // predate the feature still return `{manager: '', worker: ''}` via
  // the DEFAULT_CONFIG merge.
  const tierLowDefault =
    (useWorkflowStore((s) => s.config.refinement_tier_low) as TierPair | undefined) ?? {
      manager: '',
      worker: '',
    };
  const tierMidDefault =
    (useWorkflowStore((s) => s.config.refinement_tier_mid) as TierPair | undefined) ?? {
      manager: '',
      worker: '',
    };
  const tierHighDefault =
    (useWorkflowStore((s) => s.config.refinement_tier_high) as TierPair | undefined) ?? {
      manager: '',
      worker: '',
    };

  const [iterations, setIterations] = useState<number>(
    defaultIterations ?? 3,
  );
  const [model, setModel] = useState<string>('');
  const [workerModel, setWorkerModel] = useState<string>('');
  // Per-session tiered toggle (spec §9.3). NOT persisted.
  const [useTiered, setUseTiered] = useState<boolean>(false);
  // Per-session local copies of the tier pairs. Initialised from the
  // store; edits in the modal stay local (we intentionally do NOT call
  // updateConfig — that path is owned by SettingsPanel).
  const [tierLow, setTierLow] = useState<TierPair>({ ...tierLowDefault });
  const [tierMid, setTierMid] = useState<TierPair>({ ...tierMidDefault });
  const [tierHigh, setTierHigh] = useState<TierPair>({ ...tierHighDefault });

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Escape closes the modal.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose, submitting]);

  const iterationsValid =
    Number.isInteger(iterations) &&
    iterations >= MIN_ITERATIONS &&
    iterations <= MAX_ITERATIONS;

  const tierState: Record<TierKey, [TierPair, (v: TierPair) => void]> = {
    refinement_tier_low: [tierLow, setTierLow],
    refinement_tier_mid: [tierMid, setTierMid],
    refinement_tier_high: [tierHigh, setTierHigh],
  };

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!iterationsValid || submitting) return;
      setSubmitting(true);
      setError(null);
      try {
        const body = useTiered
          ? {
              iterations,
              // Legacy fields omitted from payload — spec §10: backend
              // switches on `tier_*` presence; sending `null` for the
              // legacy fields is fine and matches the default shape.
              model: null,
              worker_model: null,
              tier_low: { ...tierLow },
              tier_mid: { ...tierMid },
              tier_high: { ...tierHigh },
            }
          : {
              iterations,
              model: model.trim() || null,
              worker_model: workerModel.trim() || null,
            };
        const resp = await startRefinement(runId, body);
        onStarted?.(resp.session_id);
        onClose();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSubmitting(false);
      }
    },
    [
      runId,
      iterations,
      model,
      workerModel,
      useTiered,
      tierLow,
      tierMid,
      tierHigh,
      submitting,
      iterationsValid,
      onClose,
      onStarted,
    ],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="refine-modal-title"
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className={clsx(
          'w-full rounded-xl border border-awp-border bg-awp-bg shadow-2xl',
          useTiered ? 'max-w-2xl' : 'max-w-md',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-awp-border px-5 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-awp-blue" />
            <h3
              id="refine-modal-title"
              className="text-sm font-semibold text-awp-text"
            >
              Refine run
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded p-1 text-awp-muted hover:bg-awp-border/60 hover:text-awp-text transition-colors disabled:opacity-50"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 px-5 py-4">
          <p className="text-xs text-awp-muted">
            Starts a y-axis refinement session against run{' '}
            <code className="rounded bg-awp-border/40 px-1 font-mono text-[11px] text-awp-text">
              {runId.slice(0, 12)}
            </code>
            . The current deliverable is hard-linked into each iteration's
            workspace; the manager receives a gradient prefix built from
            critique defects, gate rejections, and eval deltas.
          </p>

          {/* Iterations */}
          <label className="block">
            <span className="text-xs font-medium text-awp-text">
              Iterations
            </span>
            <input
              type="number"
              min={MIN_ITERATIONS}
              max={MAX_ITERATIONS}
              step={1}
              value={iterations}
              onChange={(e) => setIterations(Number(e.target.value))}
              disabled={submitting}
              className={clsx(
                'mt-1 w-full rounded-md border bg-awp-bg px-2.5 py-1.5 text-sm text-awp-text focus:outline-none focus:ring-1 transition-colors',
                iterationsValid
                  ? 'border-awp-border focus:border-awp-blue/60 focus:ring-awp-blue/30'
                  : 'border-awp-red/60 focus:border-awp-red focus:ring-awp-red/30',
              )}
              aria-invalid={!iterationsValid}
            />
            <span className="mt-1 block text-[10px] text-awp-muted">
              Range: {MIN_ITERATIONS}–{MAX_ITERATIONS}. Budget per iteration
              is halved from the seed's observed consumption.
            </span>
          </label>

          {/* Tier toggle (per-session, not persisted) */}
          <label className="flex items-center gap-2 select-none">
            <input
              type="checkbox"
              checked={useTiered}
              onChange={(e) => setUseTiered(e.target.checked)}
              disabled={submitting}
              className="h-3.5 w-3.5 rounded border-awp-border bg-awp-bg text-awp-blue focus:ring-awp-blue/30"
              aria-label="Use tiered models across iterations"
            />
            <span className="text-xs font-medium text-awp-text">
              Use tiered models across iterations
            </span>
          </label>

          {!useTiered && (
            <>
              {/* Manager model (free text — NO dropdown per CLAUDE.md) */}
              <label className="block">
                <span className="text-xs font-medium text-awp-text">
                  Manager model{' '}
                  <span className="font-normal text-awp-muted">(optional)</span>
                </span>
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder={seedModel ?? 'e.g. openai/gpt-5-mini'}
                  disabled={submitting}
                  className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 font-mono text-sm text-awp-text placeholder:text-awp-muted/60 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
                />
                <span className="mt-1 block text-[10px] text-awp-muted">
                  Leave blank to reuse the seed's model. Provider is auto-detected.
                </span>
              </label>

              {/* Worker model */}
              <label className="block">
                <span className="text-xs font-medium text-awp-text">
                  Worker model{' '}
                  <span className="font-normal text-awp-muted">(optional)</span>
                </span>
                <input
                  type="text"
                  value={workerModel}
                  onChange={(e) => setWorkerModel(e.target.value)}
                  placeholder={seedWorkerModel ?? 'e.g. deepseek/deepseek-chat-v3.1'}
                  disabled={submitting}
                  className="mt-1 w-full rounded-md border border-awp-border bg-awp-bg px-2.5 py-1.5 font-mono text-sm text-awp-text placeholder:text-awp-muted/60 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
                />
              </label>
            </>
          )}

          {useTiered && (
            <div
              data-testid="refine-tier-grid"
              className="rounded-lg border border-awp-border/60 bg-awp-bg/40 p-3 space-y-2"
            >
              <div className="grid grid-cols-[3rem_1fr_1fr] items-center gap-2">
                <span className="text-[10px] font-medium uppercase tracking-wide text-awp-muted">
                  Tier
                </span>
                <span className="text-[10px] font-medium uppercase tracking-wide text-awp-muted">
                  Manager
                </span>
                <span className="text-[10px] font-medium uppercase tracking-wide text-awp-muted">
                  Worker
                </span>
              </div>
              {TIER_ROWS.map((row) => {
                const [pair, setPair] = tierState[row.key];
                return (
                  <div
                    key={row.key}
                    className="grid grid-cols-[3rem_1fr_1fr] items-center gap-2"
                  >
                    <span className="text-xs font-mono font-semibold text-awp-blue">
                      {row.label}
                    </span>
                    <input
                      type="text"
                      value={pair.manager}
                      onChange={(e) =>
                        setPair({ ...pair, manager: e.target.value })
                      }
                      placeholder={row.managerPlaceholder}
                      disabled={submitting}
                      className="w-full rounded-md border border-awp-border bg-awp-panel px-2 py-1 text-[11px] font-mono text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
                    />
                    <input
                      type="text"
                      value={pair.worker}
                      onChange={(e) =>
                        setPair({ ...pair, worker: e.target.value })
                      }
                      placeholder={row.workerPlaceholder}
                      disabled={submitting}
                      className="w-full rounded-md border border-awp-border bg-awp-panel px-2 py-1 text-[11px] font-mono text-awp-text placeholder:text-awp-muted/50 focus:border-awp-blue/60 focus:outline-none focus:ring-1 focus:ring-awp-blue/30 transition-colors"
                    />
                  </div>
                );
              })}
              <p className="text-[10px] text-awp-muted leading-relaxed pt-1">
                Low = early iterations, high = late. Empty = seed's model.
              </p>
            </div>
          )}

          {error && (
            <div className="rounded-md border border-awp-red/30 bg-awp-red/10 px-3 py-2 text-xs text-awp-red">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-awp-border px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md px-3 py-1.5 text-xs text-awp-muted hover:bg-awp-border/60 hover:text-awp-text transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!iterationsValid || submitting}
            className={clsx(
              'inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              iterationsValid && !submitting
                ? 'bg-awp-blue text-white hover:bg-awp-blue/90'
                : 'bg-awp-border/50 text-awp-muted cursor-not-allowed',
            )}
          >
            {submitting ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Starting…
              </>
            ) : (
              <>
                <Sparkles className="h-3 w-3" />
                Start refinement
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
