import { useMemo } from 'react';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { useWorkflowStore } from '@/stores/workflowStore';
import { SERIES_PALETTE, TOOLTIP_STYLE, ChartCard, EmptyState } from './_shared';

// Aggregate metric.critique.defects_by_category across every iteration and
// render as a donut. Categories sorted descending so the biggest problem
// domains visually dominate.
export function DefectCategoriesDonut() {
  const data = useWorkflowStore((s) => s.metrics.critique);

  const slices = useMemo(() => {
    const totals = new Map<string, number>();
    for (const c of data) {
      const byCat = c.defects_by_category ?? {};
      for (const [k, v] of Object.entries(byCat)) {
        totals.set(k, (totals.get(k) ?? 0) + Number(v ?? 0));
      }
    }
    const arr = Array.from(totals.entries())
      .map(([name, value]) => ({ name, value }))
      .filter((s) => s.value > 0)
      .sort((a, b) => b.value - a.value);
    return arr;
  }, [data]);

  if (!slices.length) {
    return (
      <ChartCard title="Defect categories">
        <EmptyState label="No defect categories yet" />
      </ChartCard>
    );
  }

  const total = slices.reduce((s, x) => s + x.value, 0);

  return (
    <ChartCard title="Defect categories" subtitle={`total ${total}`}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
          <Pie
            data={slices}
            dataKey="value"
            nameKey="name"
            innerRadius="50%"
            outerRadius="80%"
            paddingAngle={1}
            isAnimationActive={false}
          >
            {slices.map((_, i) => (
              <Cell key={i} fill={SERIES_PALETTE[i % SERIES_PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 10, color: 'var(--awp-muted, #8b949e)' }} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export default DefectCategoriesDonut;
