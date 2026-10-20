"use client";

import { ArrowRight, CheckCircle2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import { useRunChanges } from "@/hooks/use-run-changes";

type Run = { id: string; task_text: string };

// Waits for the project's first captured run, live (Supabase Realtime, RLS applies).
export function FirstRunListener({ projectId }: { projectId: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const status = useRunChanges(projectId, (payload) => {
    if (payload.eventType === "INSERT") setRun(payload.new as Run);
  });
  const connected = status === "live";

  return (
    <div className="surface relative overflow-hidden rounded-xl p-5">
      <AnimatePresence mode="wait">
        {run ? (
          <motion.div
            key="arrived"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex items-center gap-4"
          >
            <motion.div
              initial={{ scale: 0, rotate: -30 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 16 }}
              className="flex size-11 items-center justify-center rounded-full bg-success/15 ring-1 ring-success/30"
            >
              <CheckCircle2 className="size-5 text-success" />
            </motion.div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">First run captured</p>
              <p className="truncate font-mono text-xs text-muted-foreground">{run.task_text}</p>
            </div>
            <Link
              href={`/p/${projectId}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-[13px] font-medium text-primary-foreground"
            >
              Open dashboard <ArrowRight className="size-3.5" />
            </Link>
          </motion.div>
        ) : (
          <motion.div key="waiting" exit={{ opacity: 0 }} className="flex items-center gap-4">
            <div className="relative flex size-11 items-center justify-center">
              <span className="absolute inset-0 rounded-full border border-brand/30" />
              <span className="absolute inset-0 rounded-full animate-pulse-ring bg-brand/25" />
              <span
                className="absolute inset-0 rounded-full animate-sweep"
                style={{ background: "conic-gradient(from 0deg, transparent 70%, oklch(0.7 0.18 285 / 55%))" }}
              />
              <span className="relative size-2 rounded-full bg-brand" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">Waiting for your first run…</p>
              <p className="text-xs text-muted-foreground">
                {connected ? "Listening live. Run your agent once with the callback attached." : "Connecting…"}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
