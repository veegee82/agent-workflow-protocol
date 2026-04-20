import React, { useEffect, useState } from "react";
import { TaskDetail, taskApi, LossPoint } from "../api/experiments";
import { LossCurveGeneric, LossPoint as LossCurvePoint } from "../components/Charts/LossCurveGeneric";

interface Props {
  taskIdKey: string;
}

export function TaskDetailView({ taskIdKey }: Props): React.ReactElement {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [series, setSeries] = useState<LossPoint[]>([]);
  const [overriding, setOverriding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [d, s] = await Promise.all([
        taskApi.detail(taskIdKey),
        taskApi.lossSeries(taskIdKey),
      ]);
      setDetail(d);
      setSeries(s);
    } catch (e: unknown) { setError(String(e)); }
  };

  useEffect(() => { void load(); }, [taskIdKey]);

  const handleOverride = async () => {
    if (!overriding || !detail) return;
    try {
      await taskApi.setBest(taskIdKey, overriding);
      setOverriding(null);
      await load();
    } catch (e: unknown) { setError(String(e)); }
  };

  if (error) return <div className="p-4 text-red-500">Error: {error}</div>;
  if (!detail) return <div className="p-4 text-slate-400">Loading…</div>;

  const variantForRole: Record<string, "seed" | "refine" | "optimize"> = {
    seed: "seed",
    refine_iter: "refine",
    optimize_epoch_run: "optimize",
  };

  const lossPoints: LossCurvePoint[] = series.map((p, i) => {
    const v = variantForRole[p.run_role ?? "seed"] ?? "seed";
    return {
      x: i + 1,
      loss: p.loss ?? null,
      run_id: p.run_id,
      variant: v,
    };
  });

  return (
    <div className="p-6 flex flex-col gap-4 overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">
          Task {String(detail.task_number).padStart(3, "0")} · {detail.slug}
        </h1>
        <div className="flex gap-2 mt-1">
          <span className={`px-2 py-0.5 rounded text-[10px] ${detail.mode === "continuation" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
            {detail.mode}
          </span>
          {detail.best_run_id && detail.best_reason && (
            <span className={`px-2 py-0.5 rounded text-[10px] ${detail.best_reason === "user_override" ? "bg-violet-100 text-violet-700" : "bg-emerald-100 text-emerald-700"}`}>
              BEST: {detail.best_reason}
            </span>
          )}
        </div>
        {detail.user_prompt && (
          <pre className="mt-2 text-xs bg-slate-50 rounded p-2 whitespace-pre-wrap">{detail.user_prompt}</pre>
        )}
        {detail.user_feedback && (
          <pre className="mt-2 text-xs bg-amber-50 rounded p-2 whitespace-pre-wrap border-l-4 border-amber-300">
            <span className="font-semibold">user_feedback: </span>{detail.user_feedback}
          </pre>
        )}
      </div>

      <LossCurveGeneric
        points={lossPoints}
        xAxisLabel="run sequence"
        title="Loss per run (seed → refine → optimize)"
      />

      <div className="bg-white rounded shadow overflow-hidden">
        <div className="px-4 py-2 text-sm font-semibold text-slate-700 border-b flex justify-between items-center">
          <span>Runs ({detail.runs.length})</span>
          {overriding ? (
            <div className="flex gap-2">
              <button
                onClick={() => void handleOverride()}
                className="text-xs bg-violet-500 text-white px-3 py-1 rounded hover:bg-violet-600"
              >
                Override BEST → {overriding.slice(0, 8)}
              </button>
              <button
                onClick={() => setOverriding(null)}
                className="text-xs bg-slate-200 text-slate-700 px-3 py-1 rounded hover:bg-slate-300"
              >
                Cancel
              </button>
            </div>
          ) : null}
        </div>
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Run</th>
              <th className="px-3 py-2 text-left">Role</th>
              <th className="px-3 py-2 text-left">Status</th>
              <th className="px-3 py-2 text-left">Loss</th>
              <th className="px-3 py-2 text-left">BEST</th>
              <th className="px-3 py-2 text-left"></th>
            </tr>
          </thead>
          <tbody>
            {detail.runs.map((r) => {
              const isBest = r.id === detail.best_run_id;
              return (
                <tr key={r.id} className={`border-t ${isBest ? "bg-emerald-50" : ""}`}>
                  <td className="px-3 py-2 font-mono">{r.id.slice(0, 12)}</td>
                  <td className="px-3 py-2">{r.run_role}</td>
                  <td className="px-3 py-2">{r.status}</td>
                  <td className="px-3 py-2 font-mono">{r.loss !== null ? r.loss.toFixed(3) : "—"}</td>
                  <td className="px-3 py-2">{isBest ? "★" : ""}</td>
                  <td className="px-3 py-2">
                    {!isBest && r.status === "complete" && (
                      <button
                        onClick={() => setOverriding(r.id)}
                        className="text-[10px] text-violet-600 hover:underline"
                      >
                        Pin as BEST
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
