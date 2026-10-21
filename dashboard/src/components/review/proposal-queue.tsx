"use client";

import { ArrowRight, Check, Loader2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/badges";
import { RelativeTime } from "@/components/relative-time";
import { Button } from "@/components/ui/button";
import { resolveProposal } from "@/lib/actions";
import type { Proposal } from "@/lib/data";
import { diffLines, snapshotText } from "@/lib/diff";
import { cn } from "@/lib/utils";

export function ProposalQueue({
  projectId,
  proposals,
  agents,
  canManage,
}: {
  projectId: string;
  proposals: Proposal[];
  agents: Record<string, string>;
  canManage: boolean;
}) {
  const [open, setOpen] = useState(proposals);
  if (proposals.length === 0) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-muted-foreground">Fleet proposals · {open.length}</h2>
      <AnimatePresence initial={false} mode="popLayout">
        {open.map((p) => (
          <motion.div key={p.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 40, transition: { duration: 0.25 } }}>
            <ProposalCard projectId={projectId} proposal={p} agents={agents} canManage={canManage} onResolved={() => setOpen((list) => list.filter((x) => x.id !== p.id))} />
          </motion.div>
        ))}
      </AnimatePresence>
    </section>
  );
}

function ProposalCard({
  projectId,
  proposal,
  agents,
  canManage,
  onResolved,
}: {
  projectId: string;
  proposal: Proposal;
  agents: Record<string, string>;
  canManage: boolean;
  onResolved: () => void;
}) {
  const [note, setNote] = useState("");
  const [choice, setChoice] = useState<boolean | null>(null);
  const [pending, startTransition] = useTransition();
  const lines = diffLines(proposal.targetSnapshot ? snapshotText(proposal.targetSnapshot) : "", snapshotText(proposal.snapshot));
  const source = proposal.sourceAgentId ? agents[proposal.sourceAgentId] : "another agent";
  const target = agents[proposal.target_agent_id] ?? "agent";

  function resolve(approve: boolean) {
    setChoice(approve);
    startTransition(async () => {
      const result = await resolveProposal(projectId, proposal.id, approve, note);
      if (result.ok) {
        toast.success(approve ? `Approved: active for ${target}` : "Proposal rejected");
        onResolved();
      } else toast.error(result.error);
    });
  }

  return (
    <article className="surface overflow-hidden rounded-xl">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 font-mono text-[12px]">
            <span className="text-muted-foreground">{source}</span>
            <ArrowRight className="size-3.5 text-brand" />
            <span>{target}</span>
            <RelativeTime iso={proposal.created_at} className="pl-2 font-sans text-[11.5px] text-faint" />
          </div>
          <Link href={`/p/${projectId}/memory/${proposal.source_playbook_id}`} className="block text-[14px] font-medium hover:underline">
            {String(proposal.snapshot.title ?? "Playbook")}
          </Link>
          <p className="text-[12px] text-faint">
            {proposal.target_playbook_id ? `Updates “${proposal.targetTitle}” with a new version` : `Adds a new playbook to ${target}`} · proposed by {proposal.proposed_by}
          </p>
          {proposal.note ? <p className="text-[12.5px] text-muted-foreground">“{proposal.note}”</p> : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {proposal.checks.length ? (
            proposal.checks.map((c) => (
              <Pill key={c.check} tone="warning" className="max-w-[320px]">
                <span className="truncate">{c.detail}</span>
              </Pill>
            ))
          ) : (
            <Pill tone="success">no warnings</Pill>
          )}
        </div>
      </div>
      <div className="grid gap-5 p-5 lg:grid-cols-[1fr_280px]">
        <pre className="max-h-72 overflow-auto rounded-lg border border-border bg-black/20 py-2 font-mono text-[12px] leading-relaxed">
          {lines.map((line, i) => (
            <div key={i} className={cn("px-3 whitespace-pre-wrap", line.kind === "added" && "bg-success/10 text-success", line.kind === "removed" && "bg-danger/10 text-danger line-through decoration-danger/40", line.kind === "same" && "text-muted-foreground")}>
              <span className="mr-3 inline-block w-3 text-faint select-none">{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span>
              {line.text}
            </div>
          ))}
        </pre>
        <div className="space-y-3">
          <p className="text-[11.5px] leading-relaxed text-faint">
            Approving makes it active for {target} right away, with you as the reviewer. Its success rate starts fresh for {target}; a regression case is created.
          </p>
          {canManage ? (
            <>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for the audit trail" maxLength={1000} className="h-8 w-full rounded-lg border border-border bg-white/[0.02] px-3 text-[12.5px] outline-none placeholder:text-faint focus:border-brand/50" />
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
            <p className="text-[11.5px] text-faint">Only owners and admins can resolve proposals.</p>
          )}
        </div>
      </div>
    </article>
  );
}
