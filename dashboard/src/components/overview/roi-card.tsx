"use client";

import { FlaskConical } from "lucide-react";
import { motion } from "motion/react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AnimatedNumber } from "@/components/fx/animated-number";
import { ChartTooltip, formatDay } from "@/components/overview/chart-tooltip";
import type { Overview } from "@/lib/data";
import { lift, MIN_HOLDOUT_EVIDENCE, rollingRates } from "@/lib/metrics";
import { cn } from "@/lib/utils";

function pct(value: number | null) {
  return value === null ? "–" : `${(value * 100).toFixed(1)}%`;
}

// Memory's measured effect: runs that received memory against the holdout group.
export function RoiCard({ overview, holdoutRate }: { overview: Overview; holdoutRate: number }) {
  const { treated, holdout } = overview.roi;
  const result = lift(treated, holdout);
  const series = rollingRates(overview.daily);
  const holdoutKnown = holdout?.known ?? 0;
  const progress = Math.min(1, holdoutKnown / MIN_HOLDOUT_EVIDENCE);

  return (
    <div className="surface relative overflow-hidden rounded-xl">
      <div className="pointer-events-none absolute -top-24 -right-24 size-64 rounded-full bg-[radial-gradient(closest-side,oklch(0.6_0.2_285/18%),transparent)]" />
      <div className="flex flex-wrap items-start justify-between gap-6 p-5 pb-2">
        <div className="space-y-1">
          <p className="text-[12.5px] text-muted-foreground">Memory lift · success rate vs holdout</p>
          {result.enoughEvidence && result.points !== null ? (
            <div className="flex items-baseline gap-2">
              <span className={cn("tabular text-[40px] leading-none font-semibold tracking-tight", result.points >= 0 ? "text-brand-gradient" : "text-danger")}>
                <AnimatedNumber value={result.points} format={(n) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}`} />
              </span>
              <span className="text-sm text-muted-foreground">points</span>
            </div>
          ) : (
            <div className="space-y-2 pt-1">
              <div className="flex items-center gap-2 text-[15px] font-medium">
                <FlaskConical className="size-4 text-brand" /> Collecting evidence
              </div>
              <div className="h-1.5 w-56 overflow-hidden rounded-full bg-white/[0.06]">
                <motion.div
                  className="h-full rounded-full bg-brand"
                  initial={{ width: 0 }}
                  animate={{ width: `${progress * 100}%` }}
                  transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
                />
              </div>
              <p className="text-[11.5px] text-faint">
                {holdoutKnown} of {MIN_HOLDOUT_EVIDENCE} holdout runs with a known outcome. {Math.round(holdoutRate * 100)}% of tasks run without memory.
              </p>
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-right">
          <Stat label="With memory" value={pct(result.treatedRate)} sub={`${treated?.known ?? 0} runs`} dot="bg-brand" />
          <Stat label="Holdout" value={pct(result.holdoutRate)} sub={`${holdoutKnown} runs`} dot="bg-chart-5" />
          {result.tokenChange !== null ? (
            <p className="col-span-2 pt-1 text-[11.5px] text-faint">
              Tokens per run{" "}
              <span className={result.tokenChange <= 0 ? "text-success" : "text-danger"}>
                {result.tokenChange <= 0 ? "" : "+"}
                {(result.tokenChange * 100).toFixed(0)}%
              </span>{" "}
              with memory
            </p>
          ) : null}
        </div>
      </div>
      <div className="px-2 pb-3">
        <ResponsiveContainer width="100%" height={190}>
          <LineChart data={series} margin={{ top: 10, right: 12, left: -4, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="oklch(1 0 0 / 6%)" />
            <XAxis dataKey="day" tickFormatter={formatDay} tickLine={false} axisLine={false} minTickGap={36} tick={{ fill: "var(--faint)", fontSize: 11 }} />
            <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={48} tick={{ fill: "var(--faint)", fontSize: 11 }} />
            <Tooltip content={<ChartTooltip unit="%" />} cursor={{ stroke: "oklch(1 0 0 / 15%)" }} />
            <Line type="monotone" dataKey="memory" name="With memory" stroke="var(--brand)" strokeWidth={2} dot={false} connectNulls animationDuration={1100} />
            <Line type="monotone" dataKey="holdout" name="Holdout" stroke="var(--chart-5)" strokeWidth={1.5} strokeDasharray="4 4" dot={false} connectNulls animationDuration={1100} />
          </LineChart>
        </ResponsiveContainer>
        <p className="px-3 text-[11px] text-faint">7-day rolling success rate. Only runs that asked for memory and have a verified outcome count.</p>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, dot }: { label: string; value: string; sub: string; dot: string }) {
  return (
    <div>
      <p className="flex items-center justify-end gap-1.5 text-[11.5px] text-muted-foreground">
        <span className={cn("size-1.5 rounded-full", dot)} /> {label}
      </p>
      <p className="tabular text-lg font-semibold">{value}</p>
      <p className="text-[11px] text-faint">{sub}</p>
    </div>
  );
}
