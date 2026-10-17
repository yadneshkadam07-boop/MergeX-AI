import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { SEVERITIES, type Severity } from "@/api/analyses";
import { SEVERITY_STYLES } from "@/lib/severity";

interface SeverityChartProps {
  counts: Partial<Record<Severity, number>>;
}

/**
 * Issues by severity.
 *
 * Every severity is plotted even at zero: the shape of the chart then means
 * the same thing between two projects, and "no criticals" is information
 * worth showing rather than a missing bar.
 */
export function SeverityChart({ counts }: SeverityChartProps) {
  const data = SEVERITIES.map((severity) => ({
    severity,
    label: SEVERITY_STYLES[severity].label,
    count: counts[severity] ?? 0,
  }));
  const total = data.reduce((sum, row) => sum + row.count, 0);

  if (total === 0) {
    return (
      <p className="text-muted-foreground py-8 text-center text-sm">
        No issues in any severity band.
      </p>
    );
  }

  return (
    <div className="h-48 w-full" data-testid="severity-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 28, top: 4, bottom: 4 }}>
          <XAxis type="number" hide domain={[0, "dataMax"]} />
          <YAxis
            type="category"
            dataKey="label"
            width={72}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
          />
          <Bar dataKey="count" radius={4} isAnimationActive={false} barSize={18}>
            {data.map((row) => (
              <Cell key={row.severity} fill={SEVERITY_STYLES[row.severity].cssVar} />
            ))}
            <LabelList
              dataKey="count"
              position="right"
              className="fill-foreground"
              style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
