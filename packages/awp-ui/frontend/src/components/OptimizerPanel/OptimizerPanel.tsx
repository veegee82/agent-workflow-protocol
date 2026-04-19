import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  RefreshCw,
  Loader2,
  AlertCircle,
  FlaskConical,
} from 'lucide-react';
import { useWorkflowStore } from '@/stores/workflowStore';
import { SuiteList } from '@/components/SuiteList/SuiteList';
import { LossCurve } from './charts/LossCurve';
import { ArtifactDeltaTimeline } from './charts/ArtifactDeltaTimeline';
import { PerTaskLossBoxplot } from './charts/PerTaskLossBoxplot';
import { ArtifactDiffDrawer } from './ArtifactDiffDrawer';

/**
 * OptimizerPanel — root of the Optimizer tab.
 *
 * Two-mode UI:
 *
 * * When no suite is selected → render ``<SuiteList />``. A click on a
 *   suite row calls ``selectSuite`` on the workflow store, which sets
 *   ``optimizerState.selectedSuiteId`` and triggers epoch loading.
 * * When a suite is selected → show the three charts plus a "Back"
 *   button that clears the selection.
 *
 * The existing SuiteList still has a "View Graph" button that pushes
 * the chained graph into Graph-Vis; this panel is the charts-only
 * view. We render the same SuiteList and simply listen for the
 * ``selectedSuiteId`` change through the store.
 */
export function OptimizerPanel() {
  const selectedSuiteId = useWorkflowStore(
    (s) => s.optimizerState.selectedSuiteId,
  );

  if (!selectedSuiteId) {
    return <OptimizerSuitePicker />;
  }
  return <OptimizerCharts suiteId={selectedSuiteId} />;
}

/**
 * Picker view: reuses the existing SuiteList but wires its row-click to
 * ``selectSuite`` via a thin wrapper. The original SuiteList keeps its
 * "View Graph" behaviour; the row itself now also navigates here.
 */
function OptimizerSuitePicker() {
  const loadSuites = useWorkflowStore((s) => s.loadSuites);
  useEffect(() => {
    // Kick off a background load so the suites slice is warm even if the
    // user clicks through fast. SuiteList has its own fetch too — that's
    // fine, it is the presentational component. Duplicate fetches are
    // cheap (one SQLite read) and both write into the same store.
    loadSuites().catch(() => {});
  }, [loadSuites]);
  return <SuiteList />;
}

function OptimizerCharts({ suiteId }: { suiteId: string }) {
  const epochs = useWorkflowStore((s) => s.optimizerState.epochs);
  const loading = useWorkflowStore((s) => s.optimizerState.loading);
  const error = useWorkflowStore((s) => s.optimizerState.error);
  const suites = useWorkflowStore((s) => s.optimizerState.suites);
  const loadSuiteEpochs = useWorkflowStore((s) => s.loadSuiteEpochs);
  const clearSuiteSelection = useWorkflowStore((s) => s.clearSuiteSelection);

  const [diffTarget, setDiffTarget] = useState<
    | { artifact: string; from_version: number; to_version: number; type: 'update' | 'rollback' }
    | null
  >(null);

  // Auto-load on mount / suiteId change if epochs are not loaded yet.
  useEffect(() => {
    if (epochs === null && !loading) {
      loadSuiteEpochs(suiteId).catch(() => {});
    }
  }, [suiteId, epochs, loading, loadSuiteEpochs]);

  const suiteMeta = useMemo(
    () => suites?.find((s) => s.id === suiteId) ?? null,
    [suites, suiteId],
  );

  const handleRefresh = useCallback(() => {
    loadSuiteEpochs(suiteId).catch(() => {});
  }, [suiteId, loadSuiteEpochs]);

  const handleMarkerClick = useCallback(
    (ev: {
      artifact: string;
      from_version: number;
      to_version: number;
      type: 'update' | 'rollback';
    }) => {
      setDiffTarget(ev);
    },
    [],
  );

  // --- Header ---------------------------------------------------------------
  const header = (
    <div className="flex items-center justify-between border-b border-awp-border bg-awp-panel/60 px-4 py-3">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={clearSuiteSelection}
          className="inline-flex items-center gap-1 rounded-md border border-awp-border bg-awp-bg px-2.5 py-1 text-[11px] text-awp-text hover:border-awp-purple/60 hover:bg-awp-purple/10"
        >
          <ArrowLeft className="h-3 w-3" />
          Back to suites
        </button>
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-awp-purple" />
          <span className="text-sm font-semibold text-awp-text">
            {suiteMeta?.name ?? suiteId}
          </span>
          {epochs !== null && (
            <span className="text-[11px] text-awp-muted">
              {epochs.length} epoch{epochs.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
      </div>
      <button
        type="button"
        onClick={handleRefresh}
        disabled={loading}
        className="inline-flex items-center gap-1 rounded-md border border-awp-border bg-awp-bg px-2.5 py-1 text-[11px] text-awp-text hover:border-awp-purple/60 hover:bg-awp-purple/10 disabled:opacity-50"
      >
        <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
        Refresh
      </button>
    </div>
  );

  // --- Body branches --------------------------------------------------------
  let body: React.ReactNode;
  if (loading && epochs === null) {
    body = (
      <div className="flex h-full w-full items-center justify-center text-sm text-awp-muted">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading epochs...
      </div>
    );
  } else if (error) {
    body = (
      <div className="mx-6 mt-6 flex items-start gap-2 rounded-md border border-awp-red/40 bg-awp-red/10 p-3 text-xs text-awp-red">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="flex-1">
          <div className="font-medium">Failed to load epochs</div>
          <div className="mt-1 text-awp-red/80">{error}</div>
          <button
            type="button"
            onClick={handleRefresh}
            className="mt-2 inline-flex items-center gap-1 rounded border border-awp-red/40 px-2 py-1 text-[11px] hover:bg-awp-red/20"
          >
            Retry
          </button>
        </div>
      </div>
    );
  } else if (!epochs || epochs.length === 0) {
    body = (
      <div className="flex h-full w-full flex-col items-center justify-center px-8 text-center text-awp-muted">
        <FlaskConical className="mb-3 h-10 w-10 text-awp-muted/50" />
        <p className="text-sm font-medium text-awp-text">
          Suite has no epochs yet.
        </p>
        <p className="mt-1 text-xs">
          Run{' '}
          <code className="rounded bg-awp-panel px-1.5 py-0.5 font-mono text-awp-text">
            awp optimize --with-textgrad
          </code>{' '}
          on this suite to start.
        </p>
      </div>
    );
  } else {
    body = (
      <div className="mx-auto max-w-6xl p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {/* Row 1: LossCurve — span both columns */}
          <div className="md:col-span-2">
            <LossCurve epochs={epochs} />
          </div>
          {/* Row 2: ArtifactDeltaTimeline — full width */}
          <div className="md:col-span-2">
            <ArtifactDeltaTimeline
              epochs={epochs}
              onMarkerClick={handleMarkerClick}
            />
          </div>
          {/* Row 3: PerTaskLossBoxplot — full width */}
          <div className="md:col-span-2">
            <PerTaskLossBoxplot epochs={epochs} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-awp-bg">
      {header}
      <div className="flex-1 overflow-auto">{body}</div>
      {diffTarget && (
        <ArtifactDiffDrawer
          artifact={diffTarget.artifact}
          fromVersion={diffTarget.from_version}
          toVersion={diffTarget.to_version}
          eventType={diffTarget.type}
          onClose={() => setDiffTarget(null)}
        />
      )}
    </div>
  );
}

export default OptimizerPanel;
