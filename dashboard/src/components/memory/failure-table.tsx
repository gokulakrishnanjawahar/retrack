"use client";

import { ChevronRight, Loader2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/badges";
import { RelativeTime } from "@/components/relative-time";
import { setUnrecoverable } from "@/lib/actions";
import type { FailureSignature } from "@/lib/data";
import { stepText } from "@/lib/diff";
import { cn } from "@/lib/utils";

export function FailureTable({
  projectId,
  failures,
  agents,
  canManage,
}: {
  projectId: string;
  failures: FailureSignature[];
  agents: Record<string, string>;
  canManage: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const most = Math.max(1, ...failures.map((f) => f.occurrences));
  if (failures.length === 0) {
    return <p className="surface rounded-xl px-6 py-14 text-center text-sm text-muted-foreground">No failure signatures yet. Repeated tool failures are grouped here, with any fix your agent found.</p>;
  }
  return (
    <div className="surface overflow-hidden rounded-xl">
      <div className="grid grid-cols-[1.4fr_1fr_160px_120px_100px_16px] gap-4 border-b border-border px-5 py-2.5 text-[11px] font-medium tracking-wide text-faint uppercase max-lg:hidden">
        <span>Failure</span>
        <span>Input shape</span>
        <span>Occurrences</span>
        <span>Known fix</span>
        <span className="text-right">Last seen</span>
        <span />
      </div>
      <ul className="divide-y divide-border">
        {failures.map((f, i) => (
          <motion.li key={f.id} initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { delay: Math.min(i * 0.02, 0.3) } }}>
            <button
              type="button"
              onClick={() => setOpen(open === f.id ? null : f.id)}
              className="grid w-full grid-cols-[1.4fr_1fr_160px_120px_100px_16px] items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-white/[0.02] max-lg:grid-cols-1 max-lg:gap-1.5"
            >
              <div className="min-w-0">
                <p className="truncate font-mono text-[12.5px]">
                  {f.tool_name} <span className="text-danger">{f.error_class}</span>
                </p>
                <p className="text-[11px] text-faint">{agents[f.agent_id] ?? "agent"}</p>
              </div>
              <code className="truncate font-mono text-[11.5px] text-muted-foreground">{f.input_shape}</code>
              <div className="flex items-center gap-2">
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/[0.05]">
                  <motion.div className="h-full rounded-full bg-danger/70" initial={{ width: 0 }} animate={{ width: `${(f.occurrences / most) * 100}%` }} transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }} />
                </div>
                <span className="tabular w-8 text-right font-mono text-[11.5px]">{f.occurrences}</span>
              </div>
              <div>
                {f.unrecoverable ? <Pill tone="danger">unrecoverable</Pill> : f.recoveries > 0 ? <Pill tone="success">{f.recoveries} recovered</Pill> : <span className="text-[11.5px] text-faint">none yet</span>}
              </div>
              <RelativeTime iso={f.last_seen} className="text-right text-[11.5px] text-faint" />
              <ChevronRight className={cn("size-3.5 text-faint transition-transform max-lg:hidden", open === f.id && "rotate-90")} />
            </button>
            <AnimatePresence initial={false}>
              {open === f.id ? (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <FailureDetail projectId={projectId} failure={f} canManage={canManage} />
                </motion.div>
              ) : null}
            </AnimatePresence>
          </motion.li>
        ))}
      </ul>
    </div>
  );
}

const CHOICES = [
  { value: null, label: "Automatic", hint: "Unrecoverable after 5 failures with no recovery" },
  { value: true, label: "Always stop", hint: "Agents stop retrying immediately" },
  { value: false, label: "Never stop", hint: "Agents may keep retrying" },
] as const;

function FailureDetail({ projectId, failure, canManage }: { projectId: string; failure: FailureSignature; canManage: boolean }) {
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  const steps = Array.isArray(failure.recovery_steps) ? failure.recovery_steps : [];
  return (
    <div className="grid gap-5 border-t border-border bg-black/15 px-5 py-4 lg:grid-cols-[1fr_320px]">
      <div className="space-y-3">
        <p className="text-[11px] font-medium tracking-wide text-faint uppercase">Known fix</p>
        {steps.length ? (
          <ol className="space-y-1.5">
            {steps.map((step, i) => (
              <li key={i} className="flex gap-2.5 text-[12.5px]">
                <span className="font-mono text-faint">{i + 1}.</span>
                <span className="text-foreground/85">{stepText(step)}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-[12.5px] text-faint">No recovery recorded yet. When an agent retries and succeeds within the same run, the fix appears here and is returned with the warning.</p>
        )}
        <p className="text-[11.5px] text-faint">
          First seen <RelativeTime iso={failure.first_seen} />
          {failure.example_run_id ? (
            <>
              {" · "}
              <Link href={`/p/${projectId}/runs/${failure.example_run_id}`} className="text-muted-foreground underline-offset-2 hover:underline">
                example run
              </Link>
            </>
          ) : null}
        </p>
      </div>
      <div className="space-y-2">
        <p className="text-[11px] font-medium tracking-wide text-faint uppercase">Circuit breaker</p>
        <div className="space-y-1.5">
          {CHOICES.map((choice) => {
            const selected = failure.unrecoverable_override === choice.value;
            return (
              <button
                key={String(choice.value)}
                type="button"
                disabled={!canManage || pending || selected}
                onClick={() =>
                  startTransition(async () => {
                    const result = await setUnrecoverable(projectId, failure.id, choice.value);
                    if (result.ok) {
                      toast.success(`Circuit breaker: ${choice.label.toLowerCase()}`);
                      router.refresh();
                    } else toast.error(result.error);
                  })
                }
                className={cn(
                  "flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-default",
                  selected ? "border-brand/50 bg-brand-soft" : "border-border enabled:hover:bg-white/[0.03]",
                )}
              >
                <span>
                  <span className="block text-[12.5px]">{choice.label}</span>
                  <span className="block text-[11px] text-faint">{choice.hint}</span>
                </span>
                {pending && !selected ? <Loader2 className="size-3.5 animate-spin text-faint" /> : null}
              </button>
            );
          })}
        </div>
        {!canManage ? <p className="text-[11px] text-faint">Only owners and admins can change this.</p> : null}
      </div>
    </div>
  );
}
