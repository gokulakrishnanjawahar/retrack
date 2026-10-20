"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, formatDay } from "@/components/overview/chart-tooltip";
import type { DailyPoint } from "@/lib/data";

export function RunsChart({ daily }: { daily: DailyPoint[] }) {
  const data = daily.map((d) => ({
    day: d.day,
    Succeeded: d.successes,
    Failed: d.failures,
    Unverified: d.runs - d.successes - d.failures,
  }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 4, left: -18, bottom: 0 }}>
        <defs>
          {[
            ["ok", "var(--success)"],
            ["bad", "var(--danger)"],
            ["unk", "var(--chart-5)"],
          ].map(([id, color]) => (
            <linearGradient key={id} id={`runs-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={color} stopOpacity={0.35} />
              <stop offset="1" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} stroke="oklch(1 0 0 / 6%)" />
        <XAxis dataKey="day" tickFormatter={formatDay} tickLine={false} axisLine={false} minTickGap={36} tick={{ fill: "var(--faint)", fontSize: 11 }} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={44} tick={{ fill: "var(--faint)", fontSize: 11 }} />
        <Tooltip content={<ChartTooltip />} cursor={{ stroke: "oklch(1 0 0 / 15%)" }} />
        <Area type="monotone" dataKey="Succeeded" stackId="1" stroke="var(--success)" strokeWidth={1.5} fill="url(#runs-ok)" animationDuration={900} />
        <Area type="monotone" dataKey="Failed" stackId="1" stroke="var(--danger)" strokeWidth={1.5} fill="url(#runs-bad)" animationDuration={900} />
        <Area type="monotone" dataKey="Unverified" stackId="1" stroke="var(--chart-5)" strokeWidth={1} fill="url(#runs-unk)" animationDuration={900} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
