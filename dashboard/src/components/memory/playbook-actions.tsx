"use client";

import { Archive, Loader2, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { setPlaybookStatus } from "@/lib/actions";

const COPY = {
  quarantined: {
    title: "Quarantine this playbook?",
    body: "Agents stop receiving it right away. It moves to the review queue, where approving it makes it active again.",
    button: "Quarantine",
  },
  retired: {
    title: "Retire this playbook?",
    body: "Agents stop receiving it and its regression case is retired. Retired playbooks are kept for the record.",
    button: "Retire",
  },
} as const;

export function PlaybookActions({ projectId, playbookId, status }: { projectId: string; playbookId: string; status: string }) {
  const [action, setAction] = useState<"quarantined" | "retired" | null>(null);
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  if (status === "retired") return null;
  return (
    <>
      {status !== "quarantined" ? (
        <Button variant="outline" onClick={() => setAction("quarantined")} className="h-8 gap-1.5">
          <ShieldAlert className="size-3.5 text-warning" /> Quarantine
        </Button>
      ) : null}
      <Button variant="outline" onClick={() => setAction("retired")} className="h-8 gap-1.5">
        <Archive className="size-3.5" /> Retire
      </Button>
      <Dialog open={action !== null} onOpenChange={(open) => (open ? null : setAction(null))}>
        <DialogContent className="sm:max-w-[440px]">
          {action ? (
            <>
              <DialogHeader>
                <DialogTitle>{COPY[action].title}</DialogTitle>
                <DialogDescription>{COPY[action].body}</DialogDescription>
              </DialogHeader>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (optional, kept in the audit trail)" maxLength={500} />
              <DialogFooter>
                <Button variant="ghost" onClick={() => setAction(null)}>
                  Cancel
                </Button>
                <Button
                  variant={action === "retired" ? "destructive" : "default"}
                  disabled={pending}
                  onClick={() =>
                    startTransition(async () => {
                      const result = await setPlaybookStatus(projectId, playbookId, action, note);
                      if (result.ok) {
                        toast.success(action === "retired" ? "Playbook retired" : "Playbook quarantined and sent to review");
                        setAction(null);
                        setNote("");
                        router.refresh();
                      } else toast.error(result.error);
                    })
                  }
                  className="min-w-24"
                >
                  {pending ? <Loader2 className="size-4 animate-spin" /> : COPY[action].button}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
