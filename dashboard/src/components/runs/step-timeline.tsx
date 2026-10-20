"use client";

import { Bot, ChevronRight, Wrench } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { StepRow } from "@/lib/data";
import { cn } from "@/lib/utils";

// The run's steps in order, with each step's share of the run's time shown as a bar.
export function StepTimeline({ steps }: { steps: StepRow[] }) {
  const longest = Math.max(1, ...steps.map((s) => s.latency_ms ?? 0));
  if (steps.length === 0) return <p className="px-5 py-8 text-sm text-muted-foreground">No steps were captured for this run.</p>;
  return (
    <ol className="relative px-5 py-4">
      <span aria-hidden className="absolute top-6 bottom-6 left-[33px] w-px bg-gradient-to-b from-border via-border to-transparent" />
      {steps.map((step, i) => (
        <StepItem key={step.idx} step={step} index={i} longest={longest} />
      ))}
    </ol>
  );
}

function StepItem({ step, index, longest }: { step: StepRow; index: number; longest: number }) {
  const [open, setOpen] = useState(false);
  const failed = Boolean(step.error_class);
  const hasDetail = Boolean(step.args_redacted && Object.keys(step.args_redacted).length) || Boolean(step.result_redacted);
  return (
    <motion.li
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: Math.min(index * 0.05, 0.6), duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="relative pb-3 pl-11 last:pb-0"
    >
      <span
        className={cn(
          "absolute top-1.5 left-0 flex size-7 items-center justify-center rounded-lg ring-1",
          failed ? "bg-danger/10 text-danger ring-danger/30" : step.type === "tool" ? "bg-brand-soft text-brand ring-brand/25" : "bg-white/[0.05] text-muted-foreground ring-border",
        )}
      >
        {step.type === "tool" ? <Wrench className="size-3.5" /> : <Bot className="size-3.5" />}
      </span>
      <button
        type="button"
        disabled={!hasDetail}
        onClick={() => setOpen((v) => !v)}
        className="w-full rounded-lg border border-transparent px-3 py-2 text-left transition-colors enabled:hover:border-border enabled:hover:bg-white/[0.02]"
      >
        <div className="flex items-center gap-2">
          <span className="font-mono text-[12.5px]">{step.type === "tool" ? step.tool_name ?? "tool" : "model call"}</span>
          {step.type === "tool" ? (
            <span className={cn("font-mono text-[10.5px]", step.input_trust === "trusted" ? "text-success" : "text-faint")}>
              {step.input_trust}
            </span>
          ) : null}
          {failed ? <span className="rounded bg-danger/10 px-1.5 font-mono text-[10.5px] text-danger">{step.error_class}</span> : null}
          {step.result_class && !failed ? <span className="font-mono text-[10.5px] text-faint">{step.result_class}</span> : null}
          <span className="tabular ml-auto font-mono text-[11px] text-faint">
            {step.tokens_in || step.tokens_out ? `${(step.tokens_in ?? 0) + (step.tokens_out ?? 0)} tok · ` : ""}
            {step.latency_ms !== null ? `${step.latency_ms} ms` : ""}
          </span>
          {hasDetail ? <ChevronRight className={cn("size-3.5 text-faint transition-transform", open && "rotate-90")} /> : null}
        </div>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/[0.04]">
          <motion.div
            className={cn("h-full rounded-full", failed ? "bg-danger/70" : step.type === "tool" ? "bg-brand/70" : "bg-white/25")}
            initial={{ width: 0 }}
            animate={{ width: `${Math.max(2, ((step.latency_ms ?? 0) / longest) * 100)}%` }}
            transition={{ delay: 0.2 + Math.min(index * 0.05, 0.6), duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
          />
        </div>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mx-3 mt-1 mb-2 space-y-2 rounded-lg border border-border bg-black/20 p-3 font-mono text-[11.5px]">
              {step.args_redacted && Object.keys(step.args_redacted).length ? (
                <div>
                  <p className="pb-1 text-faint">arguments (redacted)</p>
                  <pre className="overflow-x-auto whitespace-pre-wrap text-muted-foreground">{JSON.stringify(step.args_redacted, null, 2)}</pre>
                </div>
              ) : null}
              {step.result_redacted ? (
                <div>
                  <p className="pb-1 text-faint">result (redacted)</p>
                  <pre className="overflow-x-auto whitespace-pre-wrap text-muted-foreground">{step.result_redacted}</pre>
                </div>
              ) : null}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.li>
  );
}
