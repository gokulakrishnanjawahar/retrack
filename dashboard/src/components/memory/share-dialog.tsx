"use client";

import { Loader2, Share2 } from "lucide-react";
import Link from "next/link";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { proposePlaybook } from "@/lib/actions";
import { cn } from "@/lib/utils";

type TargetPlaybook = { id: string; agent_id: string; title: string; status: string };

// Propose this playbook to another agent: as a new playbook, or as an update of one of
// that agent's playbooks. Nothing changes until an owner or admin approves it in Review.
export function ShareDialog({
  projectId,
  playbookId,
  sourceAgentId,
  agents,
  targetPlaybooks,
}: {
  projectId: string;
  playbookId: string;
  sourceAgentId: string;
  agents: Record<string, string>;
  targetPlaybooks: TargetPlaybook[];
}) {
  const others = Object.entries(agents).filter(([id]) => id !== sourceAgentId);
  const [open, setOpen] = useState(false);
  const [agentId, setAgentId] = useState(others[0]?.[0] ?? "");
  const [targetId, setTargetId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [done, setDone] = useState(false);
  const [pending, startTransition] = useTransition();
  const candidates = targetPlaybooks.filter((p) => p.agent_id === agentId && p.status !== "retired");

  if (others.length === 0) return null;
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} className="h-8 gap-1.5">
        <Share2 className="size-3.5 text-brand" /> Share with agent
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setTimeout(() => setDone(false), 200);
        }}
      >
        <DialogContent className="sm:max-w-[480px]">
          {done ? (
            <>
              <DialogHeader>
                <DialogTitle>Proposed to {agents[agentId]}</DialogTitle>
                <DialogDescription>It waits in Review. Nothing changes for {agents[agentId]} until an owner or admin approves it.</DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="ghost" onClick={() => setOpen(false)}>
                  Close
                </Button>
                <Button asChild>
                  <Link href={`/p/${projectId}/review`}>Open Review</Link>
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Share with another agent</DialogTitle>
                <DialogDescription>Proposes this playbook as a reviewable change. The copy starts with no uses, so recall re-learns how well it works for that agent.</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>Agent</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {others.map(([id, name]) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => {
                          setAgentId(id);
                          setTargetId(null);
                        }}
                        className={cn("rounded-lg border px-3 py-1.5 font-mono text-[12px] transition-colors", agentId === id ? "border-brand/50 bg-brand-soft" : "border-border hover:bg-white/[0.03]")}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>As</Label>
                  <div className="max-h-48 space-y-1.5 overflow-y-auto">
                    <Choice selected={targetId === null} onClick={() => setTargetId(null)} title="A new playbook" hint={`Adds it to ${agents[agentId] ?? "the agent"}'s memory`} />
                    {candidates.map((p) => (
                      <Choice key={p.id} selected={targetId === p.id} onClick={() => setTargetId(p.id)} title={`Update: ${p.title}`} hint={`Replaces this ${p.status} playbook's content with a new version`} />
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="share-note">Why (shown to the reviewer)</Label>
                  <Input id="share-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="Same refund flow; billing-agent keeps failing it" />
                </div>
              </div>
              <DialogFooter>
                <Button variant="ghost" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button
                  disabled={pending || !agentId}
                  onClick={() =>
                    startTransition(async () => {
                      const result = await proposePlaybook(projectId, playbookId, { targetAgentId: agentId, targetPlaybookId: targetId, note });
                      if (result.ok) setDone(true);
                      else toast.error(result.error);
                    })
                  }
                  className="min-w-28"
                >
                  {pending ? <Loader2 className="size-4 animate-spin" /> : "Propose"}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function Choice({ selected, onClick, title, hint }: { selected: boolean; onClick: () => void; title: string; hint: string }) {
  return (
    <button type="button" onClick={onClick} className={cn("w-full rounded-lg border px-3 py-2 text-left transition-colors", selected ? "border-brand/50 bg-brand-soft" : "border-border hover:bg-white/[0.03]")}>
      <span className="block truncate text-[12.5px]">{title}</span>
      <span className="block text-[11px] text-faint">{hint}</span>
    </button>
  );
}
