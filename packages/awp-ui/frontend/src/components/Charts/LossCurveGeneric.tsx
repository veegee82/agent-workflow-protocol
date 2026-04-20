import React from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

export interface LossPoint {
  x: number | string;
  loss: number | null;
  label?: string;
  variant?: "seed" | "refine" | "optimize" | "update" | "rollback";
  run_id?: string;
}

const VARIANT_COLOR: Record<NonNullable<LossPoint["variant"]>, string> = {
  seed:     "#8b5cf6",
  refine:   "#f59e0b",
  optimize: "#3b82f6",
  update:   "#10b981",
  rollback: "#ef4444",
};

export function LossCurveGeneric({
  points, xAxisLabel, title,
}: {
  points: LossPoint[];
  xAxisLabel: string;
  title: string;
}): React.ReactElement {
  // Filter out null losses for charting — they're legitimately unknown.
  const data = points
    .filter((p) => p.loss !== null)
    .map((p) => ({ ...p, loss: p.loss as number }));

  return (
    <div className="w-full h-64 bg-white rounded shadow p-3">
      <div className="text-sm font-semibold text-slate-700 mb-2">{title}</div>
      {data.length === 0 ? (
        <div className="flex items-center justify-center h-48 text-slate-400 text-xs">
          No runs with a loss yet
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="x" label={{ value: xAxisLabel, position: "insideBottom", offset: -5 }} />
            <YAxis domain={[0, 1]} label={{ value: "loss", angle: -90, position: "insideLeft" }} />
            <Tooltip formatter={(v: any) => (typeof v === "number" ? v.toFixed(3) : v)} />
            <Legend />
            <Line
              type="monotone"
              dataKey="loss"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={({ cx, cy, payload }: { cx?: number; cy?: number; payload?: unknown }) => {
                if (!cx || !cy) return null;
                const p = payload as Record<string, unknown> | undefined;
                if (!p) return null;
                const key = `${String(p.run_id ?? p.x)}-dot`;
                const variant = p.variant as string | undefined;
                const color = variant && variant in VARIANT_COLOR
                  ? VARIANT_COLOR[variant as NonNullable<LossPoint["variant"]>]
                  : "#3b82f6";
                return <circle key={key} cx={cx} cy={cy} r={4} fill={color} />;
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
