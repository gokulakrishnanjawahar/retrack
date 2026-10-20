"use client";

import { CheckCircle2, CircleDashed, Loader2, ShieldAlert, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { LiveDot } from "@/components/fx/live-dot";
import { useNow } from "@/hooks/use-now";
import { useRunChanges } from "@/hooks/use-run-changes";
import type { RunRow } from "@/lib/data";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const MAX_ROWS = 12;
// The pipeline normally verifies a run within a couple of minutes (Cron drains every minute).
const PROCESSING_MS = 3 * 60 * 1000;

function pick(row: Record<string, unknown>): RunRow {
  return {
    id: row.id as string,
    agent_id: row.agent_id as string,
    task_text: row.task_text as string,
    model_id: row.model_id as string,
    outcome: row.outcome as RunRow["outcome"],
    outcome_source: (row.outcome_source as string) ?? null,
    taint_level: row.taint_level as RunRow["taint_level"],
    holdout: Boolean(row.holdout),
    recalled_playbook_ids: (row.recalled_playbook_ids as string[]) ?? [],
    tokens_in: Number(row.tokens_in ?? 0),
    tokens_out: Number(row.tokens_out ?? 0),
    latency_ms: (row.latency_ms as number) ?? null,
    created_at: row.created_at as string,
  };
}

// The project's most recent runs, updated live: new runs slide in, outcomes flip as the
// pipeline verifies them. Row-level security applies to the Realtime stream.
export function LiveRunFeed({
  projectId,
  initialRuns,
  agents,
}: {
  projectId: string;
  initialRuns: RunRow[];
  agents: Record<string, string>;
}) {
  const [runs, setRuns] = useState(initialRuns);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [arrived, setArrived] = useState(0);
  const now = useNow(15_000);

  const status = useRunChanges(projectId, (payload) => {
    if (payload.eventType === "INSERT") {
      const run = pick(payload.new);
      setRuns((current) => [run, ...current.filter((r) => r.id !== run.id)].slice(0, MAX_ROWS));
      setArrived((n) => n + 1);
      setFresh((s) => new Set(s).add(run.id));
      setTimeout(() => setFresh((s) => { const next = new Set(s); next.delete(run.id); return next; }), 2500);
    } else if (payload.eventType === "UPDATE") {
      const run = pick(payload.new);
      setRuns((current) => current.map((r) => (r.id === run.id ? run : r)));
    }
  });

  return (
    <div className="surface overflow-hidden rounded-xl">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <p className="text-[13.5px] font-medium">Live runs</p>
          <AnimatePresence>
            {arrived > 0 ? (
              <motion.span
                key={arrived}
                initial={{ scale: 0.6, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="rounded-full bg-brand-soft px-1.5 py-px font-mono text-[10.5px] text-brand ring-1 ring-brand/30"
              >
                +{arrived}
              </motion.span>
            ) : null}
          </AnimatePresence>
        </div>
        <span className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
          <LiveDot tone={status === "live" ? "live" : status === "offline" ? "warning" : "idle"} pulse={status === "live"} />
          {status === "live" ? "Streaming" : status === "offline" ? "Reconnecting" : "Connecting"}
        </span>
      </div>
      {runs.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-muted-foreground">No runs yet. They appear here the moment your agent sends one.</p>
      ) : (
        <ul className="divide-y divide-border">
          <AnimatePresence initial={false}>
            {runs.map((run) => (
              <motion.li
                key={run.id}
                layout
                initial={{ opacity: 0, y: -12, backgroundColor: "oklch(0.7 0.18 285 / 0)" }}
                animate={{
                  opacity: 1,
                  y: 0,
                  backgroundColor: fresh.has(run.id) ? "oklch(0.7 0.18 285 / 0.08)" : "oklch(0.7 0.18 285 / 0)",
                }}
                exit={{ opacity: 0 }}
                transition={{ type: "spring", stiffness: 380, damping: 34, backgroundColor: { duration: 1.2 } }}
                className="grid grid-cols-[20px_1fr_auto] items-center gap-3 px-5 py-3 md:grid-cols-[20px_1fr_140px_120px_90px]"
              >
                <OutcomeIcon run={run} processing={now - new Date(run.created_at).getTime() < PROCESSING_MS} />
                <div className="min-w-0">
                  <p className="truncate text-[13px]">{run.task_text}</p>
                  <p className="truncate font-mono text-[11px] text-faint">
                    {agents[run.agent_id] ?? run.agent_id.slice(0, 8)} · {run.model_id}
                  </p>
                </div>
                <div className="hidden md:block">
                  <MemoryChip run={run} />
                </div>
                <p className="tabular hidden text-right font-mono text-[11.5px] text-muted-foreground md:block">
                  {(run.tokens_in + run.tokens_out).toLocaleString("en-US")} tok
                  {run.latency_ms ? <span className="text-faint"> · {(run.latency_ms / 1000).toFixed(1)}s</span> : null}
                </p>
                <p className="text-right text-[11.5px] text-faint" suppressHydrationWarning>
                  {timeAgo(run.created_at, now)}
                </p>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}

function OutcomeIcon({ run, processing }: { run: RunRow; processing: boolean }) {
  const key = run.taint_level === "quarantined" ? "quarantined" : run.outcome;
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.span
        key={key}
        initial={{ scale: 0.4, opacity: 0, rotate: -30 }}
        animate={{ scale: 1, opacity: 1, rotate: 0 }}
        exit={{ scale: 0.4, opacity: 0 }}
        transition={{ type: "spring", stiffness: 420, damping: 18 }}
        className="flex"
        title={key}
      >
        {key === "quarantined" ? (
          <ShieldAlert className="size-4 text-warning" />
        ) : key === "success" ? (
          <CheckCircle2 className="size-4 text-success" />
        ) : key === "failure" ? (
          <XCircle className="size-4 text-danger" />
        ) : processing ? (
          <Loader2 className="size-4 animate-spin text-faint" />
        ) : (
          <CircleDashed className="size-4 text-faint" />
        )}
      </motion.span>
    </AnimatePresence>
  );
}

function MemoryChip({ run }: { run: RunRow }) {
  const n = run.recalled_playbook_ids.length;
  if (run.holdout) {
    return <span className="rounded-full px-2 py-0.5 font-mono text-[10.5px] text-muted-foreground ring-1 ring-border">holdout</span>;
  }
  return n > 0 ? (
    <span className={cn("rounded-full bg-brand-soft px-2 py-0.5 font-mono text-[10.5px] text-brand ring-1 ring-brand/25")}>
      {n} playbook{n === 1 ? "" : "s"}
    </span>
  ) : (
    <span className="font-mono text-[10.5px] text-faint">no memory</span>
  );
}
