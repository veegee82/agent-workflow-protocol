import { useCallback, useEffect, useRef, useState } from 'react';
import { Trophy, Clock, AlertCircle, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { getRefinementSessions } from '@/api/client';
import type {
  RefinementBestManifest,
  RefinementSession,
} from '@/types';

/**
 * RefinementSessionsList — history panel for a seed run's refinement sessions.
 *
 * Polling: every 5 s while any session has no `completed_at`. Stops polling
 * as soon as every session is terminal (matches the backend's single-shot
 * daemon-thread execution model).
 */
export interface RefinementSessionsListProps {
  runId: string;
  /** Optional class applied to the outer container. */
  className?: string;
}

const POLL_INTERVAL_MS = 5000;

export function RefinementSessionsList({
  runId,
  className,
}: RefinementSessionsListProps) {
  const [sessions, setSessions] = useState<RefinementSession[]>([]);
  const [best, setBest] = useState<RefinementBestManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const fetchOnce = useCallback(async () => {
    try {
      const data = await getRefinementSessions(runId);
      setSessions(data.sessions ?? []);
      setBest(data.best ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [runId]);

  // Initial fetch + polling loop. Stops as soon as every session is terminal.
  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      if (cancelled) return;
      await fetchOnce();
      if (cancelled) return;
      const anyActive = sessions.some((s) => !s.completed_at);
      if (anyActive) {
        timerRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
      }
    };

    tick();
    return () => {
      cancelled = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // Intentionally excluding `sessions` from deps to avoid resetting the
    // timer on every fetch. The tick function reads `sessions` at call
    // time so polling stops within one iteration after everything completes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchOnce]);

  if (loading && sessions.length === 0 && !error) {
    return (
      <div className={clsx('flex items-center gap-2 px-3 py-4 text-xs text-awp-muted', className)}>
        <Loader2 className="h-3 w-3 animate-spin" />
        Loading refinement history…
      </div>
    );
  }

  if (error) {
    return (
      <div className={clsx('flex items-center gap-2 px-3 py-4 text-xs text-awp-red', className)}>
        <AlertCircle className="h-3 w-3" />
        {error}
      </div>
    );
  }

  if (sessions.length === 0 && !best) {
    return (
      <div className={clsx('px-3 py-4 text-xs text-awp-muted italic', className)}>
        No refinement sessions yet for this run.
      </div>
    );
  }

  return (
    <div className={clsx('space-y-3', className)}>
      {best && <BestBadge best={best} />}
      {sessions.map((session) => (
        <SessionCard key={session.session_id} session={session} />
      ))}
    </div>
  );
}

function BestBadge({ best }: { best: RefinementBestManifest }) {
  const delta = best.seed_loss - best.best_loss;
  return (
    <div className="flex items-center gap-3 rounded-lg border border-awp-green/40 bg-awp-green/10 px-3 py-2">
      <Trophy className="h-4 w-4 shrink-0 text-awp-green" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 text-xs">
          <span className="font-semibold text-awp-green">
            BEST loss: {best.best_loss.toFixed(4)}
          </span>
          <span className="text-awp-muted">
            seed: {best.seed_loss.toFixed(4)}
          </span>
          <span
            className={clsx(
              'font-medium',
              delta > 0 ? 'text-awp-green' : 'text-awp-red',
            )}
          >
            Δ {delta > 0 ? '-' : '+'}
            {Math.abs(delta).toFixed(4)}
          </span>
        </div>
        <div className="mt-0.5 truncate text-[10px] text-awp-muted">
          Winner: <span className="font-mono">{best.best_run_id}</span>
          {' · '}
          Session: <span className="font-mono">{best.session_id}</span>
        </div>
      </div>
    </div>
  );
}

function SessionCard({ session }: { session: RefinementSession }) {
  const terminal = Boolean(session.completed_at);
  return (
    <div className="rounded-lg border border-awp-border bg-awp-bg">
      <div className="flex items-center justify-between border-b border-awp-border/40 px-3 py-2">
        <div className="flex items-center gap-2">
          {terminal ? (
            <Clock className="h-3 w-3 text-awp-muted" />
          ) : (
            <Loader2 className="h-3 w-3 animate-spin text-awp-blue" />
          )}
          <span className="font-mono text-[11px] text-awp-text">
            {session.session_id}
          </span>
        </div>
        <span
          className={clsx(
            'rounded-full border px-2 py-0.5 text-[10px] font-medium',
            terminal
              ? 'border-awp-muted/30 bg-awp-muted/10 text-awp-muted'
              : 'border-awp-blue/30 bg-awp-blue/10 text-awp-blue',
          )}
        >
          {terminal ? session.stop_reason : 'running'}
        </span>
      </div>

      <div className="px-3 py-2 text-[11px] text-awp-muted">
        best_iter: <span className="font-medium text-awp-text">{session.best_iter}</span>
        {' · '}
        iterations: <span className="font-medium text-awp-text">{session.iterations.length}</span>
      </div>

      {session.iterations.length > 0 && (
        <div className="border-t border-awp-border/30">
          <table className="w-full text-[11px]">
            <thead className="bg-awp-border/10 text-awp-muted">
              <tr>
                <th className="px-3 py-1 text-left font-normal">k</th>
                <th className="px-3 py-1 text-left font-normal">run_id</th>
                <th className="px-3 py-1 text-right font-normal">loss</th>
                <th className="px-3 py-1 text-left font-normal">status</th>
              </tr>
            </thead>
            <tbody>
              {session.iterations.map((it) => {
                const isBest = it.k === session.best_iter;
                return (
                  <tr
                    key={it.k}
                    className={clsx(
                      'border-t border-awp-border/20',
                      isBest && 'bg-awp-green/5',
                    )}
                  >
                    <td className="px-3 py-1 font-medium text-awp-text">
                      {it.k}
                      {isBest && <span className="ml-1 text-awp-green">★</span>}
                    </td>
                    <td className="truncate px-3 py-1 font-mono text-awp-text">
                      {it.run_id}
                    </td>
                    <td className="px-3 py-1 text-right font-mono text-awp-text">
                      {it.loss.toFixed(4)}
                    </td>
                    <td className="px-3 py-1 text-awp-muted">{it.status}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
