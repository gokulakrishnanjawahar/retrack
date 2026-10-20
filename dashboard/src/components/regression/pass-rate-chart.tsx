"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TestRun } from "@/lib/data";

export function PassRateChart({ runs, threshold = 90 }: { runs: TestRun[]; threshold?: number }) {
  const data = [...runs].reverse().map((r) => ({
    at: new Date(r.at).toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
    rate: Math.round((r.passed / Math.max(1, r.total)) * 1000) / 10,
    label: `${r.passed}/${r.total}`,
    model: r.model ?? "",
  }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
        <XAxis dataKey="at" tickLine={false} axisLine={false} tick={{ fill: "var(--faint)", fontSize: 11 }} minTickGap={20} />
        <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={44} tick={{ fill: "var(--faint)", fontSize: 11 }} />
        <Tooltip
          cursor={{ fill: "oklch(1 0 0 / 4%)" }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <div className="rounded-lg border border-border bg-popover/95 px-3 py-2 text-[12px] shadow-xl backdrop-blur">
                <p className="font-mono text-[11px] text-faint">{payload[0].payload.at} · {payload[0].payload.model}</p>
                <p>
                  <span className="tabular font-medium">{payload[0].payload.rate}%</span>{" "}
                  <span className="text-muted-foreground">passed ({payload[0].payload.label})</span>
                </p>
              </div>
            ) : null
          }
        />
        <Bar dataKey="rate" radius={[4, 4, 0, 0]} animationDuration={900}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.rate >= threshold ? "var(--success)" : "var(--warning)"} fillOpacity={0.75} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
