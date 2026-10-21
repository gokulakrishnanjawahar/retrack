"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { AnimatedNumber } from "@/components/fx/animated-number";
import { Sparkline } from "@/components/overview/sparkline";
import { cn } from "@/lib/utils";

const FORMATS = {
  number: (n: number) => Math.round(n).toLocaleString("en-US"),
  percent: (n: number) => `${n.toFixed(1)}%`,
  ms: (n: number) => `${Math.round(n)} ms`,
  usd: (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
  compact: (n: number) => Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n),
};

export function KpiCard({
  label,
  value,
  format = "number",
  delta,
  deltaLabel,
  goodWhenUp = true,
  spark,
  footnote,
  index = 0,
}: {
  label: string;
  value: number | null;
  format?: keyof typeof FORMATS;
  delta?: number | null;
  deltaLabel?: string;
  goodWhenUp?: boolean;
  spark?: number[];
  footnote?: ReactNode;
  index?: number;
}) {
  const up = (delta ?? 0) >= 0;
  const good = up === goodWhenUp;
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="surface group relative overflow-hidden rounded-xl p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[12.5px] text-muted-foreground">{label}</p>
        {delta !== undefined && delta !== null ? (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-mono text-[10.5px] ring-1",
              good ? "bg-success/10 text-success ring-success/20" : "bg-danger/10 text-danger ring-danger/20",
            )}
          >
            {up ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
            {deltaLabel}
          </span>
        ) : null}
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="tabular text-[28px] leading-none font-semibold tracking-tight">
          {value === null ? <span className="text-faint">–</span> : <AnimatedNumber value={value} format={FORMATS[format]} />}
        </div>
        {spark ? <Sparkline values={spark} className="h-9 w-28 opacity-90" /> : null}
      </div>
      {footnote ? <p className="mt-3 text-[11.5px] text-faint">{footnote}</p> : null}
    </motion.div>
  );
}
