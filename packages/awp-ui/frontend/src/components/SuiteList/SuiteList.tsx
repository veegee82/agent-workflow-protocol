import { useCallback, useEffect, useState } from 'react';
import {
  FlaskConical,
  TrendingDown,
  Loader2,
  GitBranch,
  LineChart as LineChartIcon,
} from 'lucide-react';
import * as api from '@/api/client';
import type { SuiteSummary } from '@/api/client';
import { useWorkflowStore } from '@/stores/workflowStore';
import type { Edge, Node } from 'reactflow';
import type { AgentEdge, AgentNode } from '@/types';

/**
 * Optimizer tab root component.
 *
 * Lists every task suite tracked by the outer-loop DB (~/.awp/outer_loop.db,
 * overridable via $AWP_OUTER_LOOP_DB). Clicking "View Graph" on a row
 * pushes the suite's chained graph into the workflow store and switches
 * to the Graph Vis tab.
 */
export function SuiteList() {
  const [suites, setSuites] = useState<SuiteSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSuiteId, setActiveSuiteId] = useState<string | null>(null);
  const [loadingSuiteId, setLoadingSuiteId] = useState<string | null>(null);
  const setActivePanel = useWorkflowStore((s) => s.setActivePanel);
  const selectSuiteInStore = useWorkflowStore((s) => s.selectSuite);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await api.listSuites();
        if (cancelled) return;
        setSuites(rows);
      } catch (e) {
        if (cancelled) return;
        setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadSuiteGraph = useCallback(
    async (suiteId: string) => {
      setLoadingSuiteId(suiteId);
      try {
        const graph = await api.fetchSuiteGraph(suiteId);
        pushSuiteGraphToStore(graph.nodes, graph.edges);
        setActiveSuiteId(suiteId);
        setActivePanel('graphvis');
      } catch (e) {
        setError(String(e));
      } finally {
        setLoadingSuiteId(null);
      }
    },
    [setActivePanel],
  );

  // Open the OptimizerPanel charts for this suite. The Optimizer tab's
  // root component (OptimizerPanel) re-renders based on
  // ``optimizerState.selectedSuiteId`` so we just update the store; we
  // do NOT switch tabs because the user is already on the Optimizer tab.
  const openCharts = useCallback(
    (suiteId: string) => {
      setActiveSuiteId(suiteId);
      selectSuiteInStore(suiteId).catch((e) => setError(String(e)));
    },
    [selectSuiteInStore],
  );

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center text-awp-muted text-sm">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading suites...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full w-full items-center justify-center text-awp-red text-sm">
        Failed to load suites: {error}
      </div>
    );
  }

  if (!suites || suites.length === 0) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center text-awp-muted">
        <FlaskConical className="mb-3 h-10 w-10 text-awp-muted/50" />
        <p className="text-sm font-medium text-awp-text">
          No optimizer runs yet.
        </p>
        <p className="mt-1 text-xs">
          Run{' '}
          <code className="rounded bg-awp-panel px-1.5 py-0.5 font-mono text-awp-text">
            awp optimize --with-textgrad
          </code>{' '}
          to start.
        </p>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-auto bg-awp-bg">
      <div className="mx-auto max-w-5xl p-6">
        <div className="mb-4 flex items-center gap-2">
          <FlaskConical className="h-5 w-5 text-awp-purple" />
          <h2 className="text-base font-semibold text-awp-text">
            Optimizer Suites
          </h2>
          <span className="text-xs text-awp-muted">
            ({suites.length} suite{suites.length === 1 ? '' : 's'})
          </span>
        </div>

        <div className="overflow-hidden rounded-lg border border-awp-border bg-awp-panel">
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-awp-bg/50 text-awp-muted">
              <tr>
                <th className="w-[30%] px-4 py-2 font-medium">Name</th>
                <th className="w-[14%] px-4 py-2 font-medium">Epochs</th>
                <th className="w-[16%] px-4 py-2 font-medium">Latest Loss</th>
                <th className="w-[14%] px-4 py-2 font-medium">Date</th>
                <th className="w-[26%] px-4 py-2 text-right font-medium">
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {suites.map((suite) => {
                const isActive = suite.id === activeSuiteId;
                const isLoading = suite.id === loadingSuiteId;
                return (
                  <tr
                    key={suite.id}
                    className={`border-t border-awp-border/40 transition-colors ${
                      isActive ? 'bg-awp-purple/5' : 'hover:bg-awp-bg/30'
                    }`}
                  >
                    <td className="truncate px-4 py-3 text-awp-text">
                      {suite.name}
                    </td>
                    <td className="px-4 py-3 text-awp-muted">
                      {suite.epoch_count}
                      {suite.latest_epoch != null && (
                        <span className="ml-1 text-[10px] text-awp-muted/70">
                          (latest #{suite.latest_epoch})
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-awp-muted">
                      {suite.latest_mean_loss != null ? (
                        <span className="flex items-center gap-1">
                          <TrendingDown className="h-3 w-3 text-awp-green" />
                          {suite.latest_mean_loss.toFixed(3)}
                        </span>
                      ) : (
                        <span className="text-awp-muted/50">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-awp-muted">
                      {formatDate(suite.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      <div className="inline-flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => openCharts(suite.id)}
                          className="inline-flex items-center gap-1 rounded-md border border-awp-border bg-awp-bg px-2.5 py-1 text-[11px] text-awp-text hover:border-awp-purple/60 hover:bg-awp-purple/10"
                        >
                          <LineChartIcon className="h-3 w-3" />
                          Charts
                        </button>
                        <button
                          type="button"
                          onClick={() => loadSuiteGraph(suite.id)}
                          disabled={isLoading}
                          className="inline-flex items-center gap-1 rounded-md border border-awp-border bg-awp-bg px-2.5 py-1 text-[11px] text-awp-text hover:border-awp-purple/60 hover:bg-awp-purple/10 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {isLoading ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <GitBranch className="h-3 w-3" />
                          )}
                          Graph
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString();
  } catch {
    return iso;
  }
}

/** Replace the store graph with a freshly-fetched suite graph.
 *
 * We reuse the same graphNodes / graphEdges slice that powers
 * GraphVisPanel so the Graph Vis tab renders the chained view without
 * any additional plumbing. The backend emits React-Flow-ready nodes
 * (including the epochMarker type), so the mapping is a thin shape
 * translation — same logic as loadRunGraph() in workflowStore. */
function pushSuiteGraphToStore(
  apiNodes: AgentNode[],
  apiEdges: AgentEdge[],
): void {
  const nodes: Node[] = apiNodes.map((n) => {
    const raw = n as unknown as Record<string, unknown>;
    const node: Node = {
      id: n.id,
      type: (n.type as string | undefined) || 'default',
      position:
        (raw.position as { x: number; y: number }) ?? { x: 0, y: 0 },
      data: { ...n.data, nodeType: n.type },
    };
    if (raw.style) (node as unknown as Record<string, unknown>).style = raw.style;
    if (raw.parentNode)
      (node as unknown as Record<string, unknown>).parentNode = raw.parentNode;
    if (raw.extent)
      (node as unknown as Record<string, unknown>).extent = raw.extent;
    if (typeof raw.zIndex === 'number')
      (node as unknown as Record<string, unknown>).zIndex = raw.zIndex;
    return node;
  });
  const edges: Edge[] = apiEdges.map((e) => {
    const raw = e as unknown as Record<string, unknown>;
    const edge: Edge = {
      id: e.id,
      source: e.source,
      target: e.target,
    };
    if (raw.style) (edge as unknown as Record<string, unknown>).style = raw.style;
    if (raw.animated)
      (edge as unknown as Record<string, unknown>).animated = raw.animated;
    if (raw.type) (edge as unknown as Record<string, unknown>).type = raw.type;
    if (raw.data) (edge as unknown as Record<string, unknown>).data = raw.data;
    return edge;
  });

  // Write directly into the store — we intentionally bypass loadRunGraph
  // because this graph is not a single run.
  useWorkflowStore.setState({
    graphNodes: nodes,
    graphEdges: edges,
  });
}
