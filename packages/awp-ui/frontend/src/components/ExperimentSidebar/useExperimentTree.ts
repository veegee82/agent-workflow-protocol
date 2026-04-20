import { useEffect, useState } from "react";
import { Experiment, ExperimentDetail, experimentApi } from "../../api/experiments";

export interface ExperimentTreeState {
  experiments: Experiment[];
  expandedIds: Set<string>;
  detailCache: Record<string, ExperimentDetail>;
  loadingIds: Set<string>;
  error: string | null;
}

export function useExperimentTree() {
  const [state, setState] = useState<ExperimentTreeState>({
    experiments: [],
    expandedIds: new Set(),
    detailCache: {},
    loadingIds: new Set(),
    error: null,
  });

  const refresh = async () => {
    try {
      const list = await experimentApi.list();
      setState((s) => ({ ...s, experiments: list, error: null }));
    } catch (e: unknown) {
      setState((s) => ({ ...s, error: String(e) }));
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const toggle = async (experimentId: string) => {
    setState((s) => {
      const expanded = new Set(s.expandedIds);
      if (expanded.has(experimentId)) expanded.delete(experimentId);
      else expanded.add(experimentId);
      return { ...s, expandedIds: expanded };
    });
    if (!state.detailCache[experimentId]) {
      setState((s) => ({ ...s, loadingIds: new Set(s.loadingIds).add(experimentId) }));
      try {
        const detail = await experimentApi.detail(experimentId);
        setState((s) => {
          const loading = new Set(s.loadingIds); loading.delete(experimentId);
          return { ...s, detailCache: { ...s.detailCache, [experimentId]: detail }, loadingIds: loading };
        });
      } catch (e: unknown) {
        setState((s) => ({ ...s, error: String(e) }));
      }
    }
  };

  return { ...state, refresh, toggle };
}
