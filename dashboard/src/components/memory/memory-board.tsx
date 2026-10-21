"use client";

import { Search } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Pill, PlaybookStatusBadge } from "@/components/badges";
import { RelativeTime } from "@/components/relative-time";
import { FailureTable } from "@/components/memory/failure-table";
import type { FailureSignature, PlaybookSummary } from "@/lib/data";
import { cn } from "@/lib/utils";

const STATUSES = ["all", "active", "candidate", "quarantined", "retired"] as const;
const PROMOTION_SUPPORT = 3; // trusted successes needed before a playbook can activate on its own

export function MemoryBoard({
  projectId,
  playbooks,
  failures,
  agents,
  canManage,
}: {
  projectId: string;
  playbooks: PlaybookSummary[];
  failures: FailureSignature[];
  agents: Record<string, string>;
  canManage: boolean;
}) {
  const [tab, setTab] = useState<"playbooks" | "failures">("playbooks");
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const [q, setQ] = useState("");
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: playbooks.length };
    for (const p of playbooks) c[p.status] = (c[p.status] ?? 0) + 1;
    return c;
  }, [playbooks]);
  const needle = q.trim().toLowerCase();
  const shown = playbooks.filter((p) => (status === "all" || p.status === status) && (!needle || p.title.toLowerCase().includes(needle)));
  const shownFailures = failures.filter((f) => !needle || `${f.tool_name} ${f.error_class} ${f.input_shape}`.toLowerCase().includes(needle));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border border-border bg-white/[0.02] p-0.5">
          {(["playbooks", "failures"] as const).map((t) => (
            <button key={t} type="button" onClick={() => setTab(t)} className={cn("relative z-10 rounded-md px-3 py-1 text-[12.5px] transition-colors", tab === t ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
              {tab === t ? <motion.span layoutId="memory-tab" className="absolute inset-0 -z-10 rounded-md bg-white/[0.07] ring-1 ring-white/10" transition={{ type: "spring", stiffness: 500, damping: 38 }} /> : null}
              {t === "playbooks" ? `Playbooks · ${playbooks.length}` : `Failure signatures · ${failures.length}`}
            </button>
          ))}
        </div>
        {tab === "playbooks" ? (
          <div className="flex flex-wrap gap-1.5">
            {STATUSES.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setStatus(s)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[12px] ring-1 transition-colors",
                  status === s ? "bg-white/[0.08] text-foreground ring-white/15" : "text-muted-foreground ring-border hover:text-foreground",
                )}
              >
                {s} <span className="tabular text-faint">{counts[s] ?? 0}</span>
              </button>
            ))}
          </div>
        ) : null}
        <div className="relative ml-auto w-full max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter" className="h-8 w-full rounded-lg border border-border bg-white/[0.02] pr-3 pl-8 text-[12.5px] outline-none placeholder:text-faint focus:border-brand/50" />
        </div>
      </div>

      {tab === "playbooks" ? (
        shown.length === 0 ? (
          <p className="surface rounded-xl px-6 py-14 text-center text-sm text-muted-foreground">
            {playbooks.length === 0 ? "No playbooks yet. They are distilled from verified successful runs." : "Nothing matches this filter."}
          </p>
        ) : (
          <motion.ul layout className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <AnimatePresence initial={false} mode="popLayout">
              {shown.map((p, i) => (
                <motion.li
                  key={p.id}
                  layout
                  initial={{ opacity: 0, scale: 0.97 }}
                  animate={{ opacity: 1, scale: 1, transition: { delay: Math.min(i * 0.02, 0.3) } }}
                  exit={{ opacity: 0, scale: 0.97 }}
                >
                  <Link href={`/p/${projectId}/memory/${p.id}`} className="surface group flex h-full flex-col gap-3 rounded-xl p-4 transition-colors hover:ring-1 hover:ring-brand/30">
                    <div className="flex items-start justify-between gap-3">
                      <p className="line-clamp-2 text-[13.5px] font-medium">{p.title}</p>
                      <PlaybookStatusBadge status={p.status} />
                    </div>
                    <p className="font-mono text-[11px] text-faint">
                      {agents[p.agent_id] ?? "agent"} · v{p.version}
                    </p>
                    {p.status === "candidate" ? (
                      <div className="space-y-1.5">
                        <div className="flex justify-between text-[11.5px]">
                          <span className="text-muted-foreground">Trusted evidence</span>
                          <span className="tabular text-faint">
                            {Math.min(p.trusted_support, PROMOTION_SUPPORT)}/{PROMOTION_SUPPORT}
                          </span>
                        </div>
                        <div className="flex gap-1">
                          {Array.from({ length: PROMOTION_SUPPORT }, (_, k) => (
                            <span key={k} className={cn("h-1 flex-1 rounded-full", k < p.trusted_support ? "bg-brand" : "bg-white/[0.06]")} />
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        <div className="flex justify-between text-[11.5px]">
                          <span className="text-muted-foreground">
                            Success when recalled <span className="tabular text-foreground">{Math.round(p.success_rate * 100)}%</span>
                          </span>
                          <span className="tabular text-faint">{p.uses} uses</span>
                        </div>
                        <div className="h-1 overflow-hidden rounded-full bg-white/[0.05]">
                          <motion.div className="h-full rounded-full bg-gradient-to-r from-brand to-success" initial={{ width: 0 }} animate={{ width: `${p.uses ? Math.round(p.success_rate * 100) : 0}%` }} transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }} />
                        </div>
                      </div>
                    )}
                    <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
                      {p.validated_models.slice(0, 2).map((m) => (
                        <Pill key={m}>{m}</Pill>
                      ))}
                      {p.untrusted_sources ? <Pill tone="warning">{p.untrusted_sources} untrusted</Pill> : null}
                      <RelativeTime iso={p.updated_at} className="ml-auto text-[11px] text-faint" />
                    </div>
                  </Link>
                </motion.li>
              ))}
            </AnimatePresence>
          </motion.ul>
        )
      ) : (
        <FailureTable projectId={projectId} failures={shownFailures} agents={agents} canManage={canManage} />
      )}
    </div>
  );
}
