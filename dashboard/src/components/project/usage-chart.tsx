"use client";

import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { ChartTooltip, formatDay } from "@/components/overview/chart-tooltip";
import type { UsageDay } from "@/lib/data";

export function UsageChart({ usage }: { usage: UsageDay[] }) {
  const data = usage.map((d) => ({ day: d.day, Runs: d.runs_captured, Recalls: d.recalls_served }));
  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 0 }} barGap={1}>
        <XAxis dataKey="day" tickFormatter={formatDay} tickLine={false} axisLine={false} minTickGap={40} tick={{ fill: "var(--faint)", fontSize: 11 }} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "oklch(1 0 0 / 4%)" }} />
        <Bar dataKey="Runs" fill="var(--brand)" fillOpacity={0.75} radius={[3, 3, 0, 0]} animationDuration={800} />
        <Bar dataKey="Recalls" fill="var(--chart-5)" fillOpacity={0.6} radius={[3, 3, 0, 0]} animationDuration={800} />
      </BarChart>
    </ResponsiveContainer>
  );
}
