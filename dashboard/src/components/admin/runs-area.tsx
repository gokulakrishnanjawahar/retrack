"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, formatDay } from "@/components/overview/chart-tooltip";

export function RunsArea({ daily }: { daily: { day: string; runs: number }[] }) {
  const data = daily.map((d) => ({ day: d.day, Runs: d.runs }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
        <defs>
          <linearGradient id="admin-runs" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--brand)" stopOpacity={0.4} />
            <stop offset="1" stopColor="var(--brand)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="oklch(1 0 0 / 6%)" />
        <XAxis dataKey="day" tickFormatter={formatDay} tickLine={false} axisLine={false} minTickGap={36} tick={{ fill: "var(--faint)", fontSize: 11 }} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={48} tick={{ fill: "var(--faint)", fontSize: 11 }} />
        <Tooltip content={<ChartTooltip />} cursor={{ stroke: "oklch(1 0 0 / 15%)" }} />
        <Area type="monotone" dataKey="Runs" stroke="var(--brand)" strokeWidth={2} fill="url(#admin-runs)" animationDuration={900} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
