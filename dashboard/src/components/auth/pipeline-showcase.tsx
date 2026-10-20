"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { AnimatedNumber } from "@/components/fx/animated-number";
import { LiveDot } from "@/components/fx/live-dot";
import { cn } from "@/lib/utils";

type Verdict = "success" | "failure" | "quarantined";

type SampleRun = { task: string; verdict: Verdict; memory: string; tool: string };

// Illustrative runs that show the pipeline end to end (labelled as sample data in the UI).
const SAMPLES: SampleRun[] = [
  { task: "Refund order #4821: item arrived damaged", verdict: "success", memory: "Playbook · refund damaged-item orders", tool: "orders_api" },
  { task: "Change address after the parcel shipped", verdict: "failure", memory: "Failure · carrier 409 already dispatched", tool: "carrier_api" },
  { task: "Summarise ticket thread for escalation", verdict: "success", memory: "Playbook · escalation summary", tool: "tickets_api" },
  { task: "Apply coupon (page text: ignore previous instructions)", verdict: "quarantined", memory: "Firewall · injection blocked", tool: "web_fetch" },
  { task: "Cancel subscription in the middle of a cycle", verdict: "success", memory: "Playbook · prorated cancellation", tool: "billing_api" },
  { task: "Reissue invoice with the new VAT number", verdict: "success", memory: "Playbook · invoice reissue", tool: "billing_api" },
  { task: "Look up order status for a guest checkout", verdict: "failure", memory: "Failure · guest orders need email lookup", tool: "orders_api" },
];

const STAGES = ["Capture", "Verify", "Distil", "Recall"] as const;

type FeedItem = SampleRun & { id: number; settled: boolean };

const VERDICT_STYLE: Record<Verdict, { label: string; className: string }> = {
  success: { label: "verified", className: "text-success bg-success/10 ring-success/25" },
  failure: { label: "failed", className: "text-danger bg-danger/10 ring-danger/25" },
  quarantined: { label: "quarantined", className: "text-warning bg-warning/10 ring-warning/25" },
};

export function PipelineShowcase() {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [counts, setCounts] = useState({ playbooks: 0, failures: 0, blocked: 0 });
  const [stage, setStage] = useState(0);

  useEffect(() => {
    let tick = 0;
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const push = () => {
      const sample = SAMPLES[tick % SAMPLES.length];
      const id = tick++;
      setFeed((items) => [{ ...sample, id, settled: false }, ...items].slice(0, 5));
      setStage(0);
      const settle = setTimeout(() => {
        setStage(1);
        setFeed((items) => items.map((it) => (it.id === id ? { ...it, settled: true } : it)));
        setCounts((c) => ({
          playbooks: c.playbooks + (sample.verdict === "success" ? 1 : 0),
          failures: c.failures + (sample.verdict === "failure" ? 1 : 0),
          blocked: c.blocked + (sample.verdict === "quarantined" ? 1 : 0),
        }));
      }, 900);
      const distil = setTimeout(() => setStage(2), 1500);
      const recall = setTimeout(() => setStage(3), 2100);
      [settle, distil, recall].forEach((t) => timers.add(t));
    };
    push();
    const interval = setInterval(push, 2600);
    return () => {
      clearInterval(interval);
      timers.forEach(clearTimeout);
    };
  }, []);

  return (
    <div className="surface relative w-full max-w-[520px] overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2 text-[13px] font-medium">
          <LiveDot />
          support-agent
          <span className="text-faint">/ production</span>
        </div>
        <span className="font-mono text-[11px] text-faint">sample data</span>
      </div>

      <ol className="relative h-[262px] space-y-1.5 overflow-hidden p-3">
        <AnimatePresence initial={false}>
          {feed.map((item) => (
            <motion.li
              key={item.id}
              layout
              initial={{ opacity: 0, y: -14, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, transition: { duration: 0.2 } }}
              transition={{ type: "spring", stiffness: 380, damping: 32 }}
              className="rounded-lg border border-border bg-white/[0.02] px-3 py-2.5"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-[13px] text-foreground/90">{item.task}</span>
                <AnimatePresence mode="wait" initial={false}>
                  {item.settled ? (
                    <motion.span
                      key="verdict"
                      initial={{ opacity: 0, scale: 0.85 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className={cn(
                        "shrink-0 rounded-full px-2 py-0.5 font-mono text-[10.5px] ring-1",
                        VERDICT_STYLE[item.verdict].className,
                      )}
                    >
                      {VERDICT_STYLE[item.verdict].label}
                    </motion.span>
                  ) : (
                    <motion.span
                      key="capturing"
                      exit={{ opacity: 0 }}
                      className="sheen shrink-0 rounded-full px-2 py-0.5 font-mono text-[10.5px] text-muted-foreground ring-1 ring-border"
                    >
                      capturing
                    </motion.span>
                  )}
                </AnimatePresence>
              </div>
              <AnimatePresence initial={false}>
                {item.settled && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="overflow-hidden"
                  >
                    <div className="flex items-center gap-2 pt-1.5 font-mono text-[11px] text-muted-foreground">
                      <span className="text-faint">{item.tool}</span>
                      <span className="text-faint">→</span>
                      <span>{item.memory}</span>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.li>
          ))}
        </AnimatePresence>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-card to-transparent" />
      </ol>

      <div className="grid grid-cols-3 border-t border-border">
        {(
          [
            ["Playbooks", counts.playbooks, "text-foreground"],
            ["Failure signatures", counts.failures, "text-foreground"],
            ["Blocked by firewall", counts.blocked, "text-warning"],
          ] as const
        ).map(([label, value, tone], i) => (
          <div key={label} className={cn("px-4 py-3", i > 0 && "border-l border-border")}>
            <div className={cn("tabular text-lg font-semibold", tone)}>
              <AnimatedNumber value={value} />
            </div>
            <div className="text-[11px] text-faint">{label}</div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-1 border-t border-border px-3 py-2.5">
        {STAGES.map((name, i) => (
          <div key={name} className="relative flex-1">
            <div
              className={cn(
                "relative z-10 py-1 text-center font-mono text-[10.5px] transition-colors duration-300",
                i === stage ? "text-foreground" : "text-faint",
              )}
            >
              {name}
            </div>
            {i === stage && (
              <motion.div
                layoutId="stage"
                className="absolute inset-0 rounded-md bg-brand-soft ring-1 ring-brand/30"
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
