import React from "react";
import { ChevronDown, ChevronRight, FlaskConical, Target } from "lucide-react";
import { useExperimentTree } from "./useExperimentTree";

interface Props {
  selectedExperimentId: string | null;
  selectedTaskId: string | null;
  onSelectExperiment: (id: string) => void;
  onSelectTask: (key: string) => void;
}

export function ExperimentSidebar({
  selectedExperimentId, selectedTaskId, onSelectExperiment, onSelectTask,
}: Props): React.ReactElement {
  const { experiments, expandedIds, detailCache, loadingIds, error, toggle } = useExperimentTree();

  return (
    <div className="flex flex-col gap-1 p-2 text-sm text-slate-700">
      {error && <div className="text-red-500 text-xs">Error: {error}</div>}
      {experiments.length === 0 && (
        <div className="text-slate-400 text-xs italic px-2 py-1">
          No experiments yet. Create one with{" "}
          <code className="text-xs">awp experiment create</code>.
        </div>
      )}
      {experiments.map((exp) => {
        const expanded = expandedIds.has(exp.id);
        const loading = loadingIds.has(exp.id);
        const detail = detailCache[exp.id];
        const selected = selectedExperimentId === exp.id && !selectedTaskId;
        return (
          <div key={exp.id} className="flex flex-col">
            <button
              onClick={() => { void toggle(exp.id); onSelectExperiment(exp.id); }}
              className={`flex items-center gap-1 px-2 py-1 rounded hover:bg-slate-100 text-left ${selected ? "bg-violet-100" : ""}`}
            >
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <FlaskConical size={14} className="text-violet-500" />
              <span className="truncate flex-1">{exp.name}</span>
            </button>
            {expanded && (
              <div className="ml-5 flex flex-col gap-0.5">
                {loading && <div className="text-xs text-slate-400 px-2">Loading…</div>}
                {detail?.tasks.map((t) => {
                  const fullKey = t.id;
                  const taskSelected = selectedTaskId === fullKey;
                  return (
                    <button
                      key={fullKey}
                      onClick={() => onSelectTask(fullKey)}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded hover:bg-slate-100 text-left ${taskSelected ? "bg-amber-100" : ""}`}
                    >
                      <Target size={12} className={t.mode === "continuation" ? "text-amber-500" : "text-slate-500"} />
                      <span className="text-xs font-mono text-slate-500">
                        {String(t.task_number).padStart(3, "0")}
                      </span>
                      <span className="truncate flex-1 text-xs">{t.slug}</span>
                      {t.best_run_id && (
                        <span className="text-[10px] text-emerald-600">★</span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
