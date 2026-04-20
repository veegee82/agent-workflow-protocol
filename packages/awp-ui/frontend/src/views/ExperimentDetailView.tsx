import React, { useEffect, useState } from "react";
import {
  ExperimentDetail, experimentApi, LossPoint,
} from "../api/experiments";
import { LossCurveGeneric, LossPoint as LossCurvePoint } from "../components/Charts/LossCurveGeneric";

interface Props {
  experimentId: string;
  onSelectTask: (taskIdKey: string) => void;
}

export function ExperimentDetailView({ experimentId, onSelectTask }: Props): React.ReactElement {
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [lossCurve, setLossCurve] = useState<LossPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [d, lc] = await Promise.all([
          experimentApi.detail(experimentId),
          experimentApi.lossCurve(experimentId),
        ]);
        setDetail(d);
        setLossCurve(lc);
      } catch (e: unknown) {
        setError(String(e));
      }
    })();
  }, [experimentId]);

  if (error) return <div className="p-4 text-red-500">Error: {error}</div>;
  if (!detail) return <div className="p-4 text-slate-400">Loading…</div>;

  const lossPoints: LossCurvePoint[] = lossCurve
    .filter((p) => p.task_number !== undefined)
    .map((p) => ({
      x: p.task_number as number,
      loss: p.best_loss ?? null,
      label: `Task ${p.task_number}`,
      variant: "seed" as const,
    }));

  return (
    <div className="p-6 flex flex-col gap-4 overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">{detail.name}</h1>
        {detail.goal && <p className="text-slate-600 mt-1">{detail.goal}</p>}
        <div className="text-xs text-slate-400 mt-1">
          {detail.tasks.length} task{detail.tasks.length === 1 ? "" : "s"} · ID: <code>{detail.id}</code>
        </div>
      </div>

      <LossCurveGeneric
        points={lossPoints}
        xAxisLabel="task number"
        title="Best loss per task (experiment trajectory)"
      />

      <div className="bg-white rounded shadow overflow-hidden">
        <div className="px-4 py-2 text-sm font-semibold text-slate-700 border-b">Tasks</div>
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">#</th>
              <th className="px-3 py-2 text-left">Mode</th>
              <th className="px-3 py-2 text-left">Slug</th>
              <th className="px-3 py-2 text-left">Prompt / Feedback</th>
              <th className="px-3 py-2 text-left">Best</th>
            </tr>
          </thead>
          <tbody>
            {detail.tasks.map((t) => (
              <tr
                key={t.id}
                onClick={() => onSelectTask(t.id)}
                className="border-t cursor-pointer hover:bg-slate-50"
              >
                <td className="px-3 py-2 font-mono">{String(t.task_number).padStart(3, "0")}</td>
                <td className="px-3 py-2">
                  <span className={`px-2 py-0.5 rounded text-[10px] ${t.mode === "continuation" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                    {t.mode}
                  </span>
                </td>
                <td className="px-3 py-2 font-mono text-slate-500">{t.slug}</td>
                <td className="px-3 py-2 truncate max-w-xs">{t.user_prompt ?? t.user_feedback ?? ""}</td>
                <td className="px-3 py-2">
                  {t.best_run_id ? (
                    <span className="text-emerald-600 font-mono text-[10px]">{t.best_run_id.slice(0, 8)}</span>
                  ) : (
                    <span className="text-slate-300">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
