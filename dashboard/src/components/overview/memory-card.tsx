"use client";

import { motion } from "motion/react";
import type { Overview, TopPlaybook } from "@/lib/data";

const SEGMENTS = [
  { key: "active", label: "Active", color: "var(--success)" },
  { key: "candidate", label: "Candidate", color: "var(--brand)" },
  { key: "quarantined", label: "Quarantined", color: "var(--warning)" },
  { key: "retired", label: "Retired", color: "var(--chart-5)" },
] as const;

export function MemoryCard({ kpis, top }: { kpis: Overview["kpis"]; top: TopPlaybook[] }) {
  const total = SEGMENTS.reduce((acc, s) => acc + (kpis.playbooks[s.key] ?? 0), 0);
  return (
    <div className="surface flex h-full flex-col rounded-xl p-5">
      <p className="text-[12.5px] text-muted-foreground">Memory</p>
      <p className="tabular pt-2 text-[28px] leading-none font-semibold">{total.toLocaleString("en-US")}</p>
      <p className="text-[11.5px] text-faint">playbooks</p>
      <div className="mt-5 flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-white/[0.05]">
        {total > 0
          ? SEGMENTS.map((s, i) => {
              const share = (kpis.playbooks[s.key] ?? 0) / total;
              return share > 0 ? (
                <motion.div
                  key={s.key}
                  className="h-full first:rounded-l-full last:rounded-r-full"
                  style={{ background: s.color }}
                  initial={{ width: 0 }}
                  animate={{ width: `${share * 100}%` }}
                  transition={{ delay: 0.2 + i * 0.08, duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
                />
              ) : null;
            })
          : null}
      </div>
      <ul className="mt-4 space-y-2">
        {SEGMENTS.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-[12.5px]">
            <span className="size-2 rounded-full" style={{ background: s.color }} />
            <span className="text-muted-foreground">{s.label}</span>
            <span className="tabular ml-auto">{kpis.playbooks[s.key] ?? 0}</span>
          </li>
        ))}
      </ul>
      {top.length ? (
        <div className="mt-6 space-y-3 border-t border-border pt-4">
          <p className="text-[11px] font-medium tracking-wide text-faint uppercase">Most recalled</p>
          <ul className="space-y-3">
            {top.map((pb, i) => (
              <li key={pb.id} className="space-y-1.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-[12.5px]">{pb.title}</span>
                  <span className="tabular shrink-0 font-mono text-[10.5px] text-faint">{pb.uses} uses</span>
                </div>
                <div className="h-1 overflow-hidden rounded-full bg-white/[0.05]">
                  <motion.div
                    className="h-full rounded-full bg-gradient-to-r from-brand to-success"
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.round(pb.success_rate * 100)}%` }}
                    transition={{ delay: 0.4 + i * 0.07, duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="mt-auto grid grid-cols-2 gap-3 border-t border-border pt-4">
        <div>
          <p className="tabular text-lg font-semibold">{kpis.failure_signatures}</p>
          <p className="text-[11px] text-faint">failure signatures</p>
        </div>
        <div>
          <p className={`tabular text-lg font-semibold ${kpis.open_reviews ? "text-warning" : ""}`}>{kpis.open_reviews}</p>
          <p className="text-[11px] text-faint">awaiting review</p>
        </div>
      </div>
    </div>
  );
}
