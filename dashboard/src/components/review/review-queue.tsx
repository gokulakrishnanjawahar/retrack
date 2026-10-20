"use client";

import { Check, CheckCircle2, Loader2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Pill, PlaybookStatusBadge } from "@/components/badges";
import { RelativeTime } from "@/components/relative-time";
import { Button } from "@/components/ui/button";
import { resolveReview } from "@/lib/actions";
import type { ReviewItem } from "@/lib/data";
import { stepText } from "@/lib/diff";

export function ReviewQueue({ projectId, items, canManage }: { projectId: string; items: ReviewItem[]; canManage: boolean }) {
  const [open, setOpen] = useState(items);
  return (
    <div className="space-y-3">
      <AnimatePresence initial={false} mode="popLayout">
        {open.length === 0 ? (
          <motion.div key="clear" initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} className="surface flex flex-col items-center gap-3 rounded-xl px-6 py-14 text-center">
            <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 260, damping: 14 }} className="flex size-12 items-center justify-center rounded-full bg-success/10 ring-1 ring-success/30">
              <CheckCircle2 className="size-6 text-success" />
            </motion.div>
            <p className="text-sm font-medium">All clear</p>
            <p className="max-w-sm text-[12.5px] text-muted-foreground">Nothing is waiting for review. Quarantined or unusual memory appears here before agents can use it.</p>
          </motion.div>
        ) : (
          open.map((item) => (
            <motion.div key={item.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 40, transition: { duration: 0.25 } }}>
              <ReviewCard projectId={projectId} item={item} canManage={canManage} onResolved={() => setOpen((list) => list.filter((i) => i.id !== item.id))} />
            </motion.div>
          ))
        )}
      </AnimatePresence>
    </div>
  );
}

function ReviewCard({ projectId, item, canManage, onResolved }: { projectId: string; item: ReviewItem; canManage: boolean; onResolved: () => void }) {
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();
  const [choice, setChoice] = useState<boolean | null>(null);
  const reasons = item.reason.split(";").map((r) => r.trim()).filter(Boolean);
  const pb = item.playbook;

  function resolve(approve: boolean) {
    setChoice(approve);
    startTransition(async () => {
      const result = await resolveReview(projectId, item.id, approve, note);
      if (result.ok) {
        toast.success(approve ? "Approved: the playbook is now active" : "Rejected: the playbook is retired");
        onResolved();
      } else toast.error(result.error);
    });
  }

  return (
    <article className="surface overflow-hidden rounded-xl">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2">
            {pb ? <PlaybookStatusBadge status={pb.status} /> : <Pill>{item.object_type}</Pill>}
            <RelativeTime iso={item.created_at} className="text-[11.5px] text-faint" />
          </div>
          {pb ? (
            <Link href={`/p/${projectId}/memory/${pb.id}`} className="block text-[14px] font-medium hover:underline">
              {pb.title}
            </Link>
          ) : (
            <p className="font-mono text-[12.5px]">{item.object_id}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {reasons.map((r) => (
            <Pill key={r} tone="warning">
              {r}
            </Pill>
          ))}
        </div>
      </div>
      <div className="grid gap-5 p-5 lg:grid-cols-[1fr_280px]">
        <div className="space-y-3">
          {pb?.task_pattern ? <p className="text-[12.5px] text-muted-foreground">{pb.task_pattern}</p> : null}
          {pb ? (
            <ol className="space-y-1.5">
              {(pb.steps as unknown[]).slice(0, 6).map((step, i) => (
                <li key={i} className="flex gap-2.5 text-[12.5px]">
                  <span className="font-mono text-faint">{i + 1}.</span>
                  <span className="text-foreground/85">{stepText(step)}</span>
                </li>
              ))}
            </ol>
          ) : null}
          {item.findings.length ? (
            <ul className="space-y-1.5 border-t border-border pt-3">
              {item.findings.map((f) => (
                <li key={f.id} className="flex items-start gap-2 text-[12px]">
                  <Pill tone={f.severity === "block" ? "danger" : "warning"}>{f.check_name}</Pill>
                  <span className="text-muted-foreground">{f.detail}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="space-y-3">
          {pb ? (
            <div className="grid grid-cols-3 gap-2 rounded-lg border border-border p-3 text-center">
              <div>
                <p className="tabular text-[15px] font-semibold">{pb.trusted_support}</p>
                <p className="text-[10.5px] text-faint">trusted</p>
              </div>
              <div>
                <p className="tabular text-[15px] font-semibold">{pb.untrusted_sources}</p>
                <p className="text-[10.5px] text-faint">untrusted</p>
              </div>
              <div>
                <p className={`tabular text-[15px] font-semibold ${pb.quarantined_sources ? "text-warning" : ""}`}>{pb.quarantined_sources}</p>
                <p className="text-[10.5px] text-faint">quarantined</p>
              </div>
            </div>
          ) : null}
          {canManage ? (
            <>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Note for the audit trail"
                maxLength={1000}
                className="h-8 w-full rounded-lg border border-border bg-white/[0.02] px-3 text-[12.5px] outline-none placeholder:text-faint focus:border-brand/50"
              />
              <div className="grid grid-cols-2 gap-2">
                <Button variant="destructive" disabled={pending} onClick={() => resolve(false)} className="h-8 gap-1.5">
                  {pending && choice === false ? <Loader2 className="size-3.5 animate-spin" /> : <X className="size-3.5" />} Reject
                </Button>
                <Button disabled={pending} onClick={() => resolve(true)} className="h-8 gap-1.5">
                  {pending && choice === true ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />} Approve
                </Button>
              </div>
            </>
          ) : (
            <p className="text-[11.5px] text-faint">Only owners and admins can resolve reviews.</p>
          )}
        </div>
      </div>
    </article>
  );
}
