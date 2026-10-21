"use client";

import { History, Loader2 } from "lucide-react";
import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { rollbackPlaybook } from "@/lib/actions";
import type { PlaybookDetail } from "@/lib/data";
import { diffLines, snapshotText } from "@/lib/diff";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export function VersionHistory({
  versions,
  liveVersion,
  restore,
}: {
  versions: PlaybookDetail["versions"];
  liveVersion: number;
  // Set when the viewer may roll back (owner or admin).
  restore?: { projectId: string; playbookId: string };
}) {
  const [selected, setSelected] = useState(versions[0]?.version ?? 1);
  const index = versions.findIndex((v) => v.version === selected);
  const shown = versions[index];
  const previous = versions[index + 1];
  const lines = shown ? diffLines(previous ? snapshotText(previous.snapshot) : "", snapshotText(shown.snapshot)) : [];

  return (
    <div className="grid md:grid-cols-[220px_1fr]">
      <ol className="border-b border-border p-2 md:border-r md:border-b-0">
        {versions.map((v) => (
          <li key={v.version}>
            <button
              type="button"
              onClick={() => setSelected(v.version)}
              className={cn("relative w-full rounded-md px-3 py-2 text-left transition-colors", v.version === selected ? "text-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              {v.version === selected ? <motion.span layoutId="version" className="absolute inset-0 rounded-md bg-white/[0.06] ring-1 ring-white/[0.06]" /> : null}
              <span className="relative flex items-center gap-2 font-mono text-[12.5px]">
                v{v.version}
                {v.version === liveVersion ? <span className="rounded bg-success/10 px-1 text-[10px] text-success">live</span> : null}
              </span>
              <span className="relative block truncate text-[11px] text-faint" title={v.change_reason}>
                {v.change_reason} · {formatDate(v.created_at)}
              </span>
            </button>
          </li>
        ))}
      </ol>
      <div className="min-w-0 p-4">
        <div className="flex items-center justify-between gap-3 pb-2">
          <p className="text-[11.5px] text-faint">
            {previous ? `Changes from v${previous.version} to v${shown?.version}` : `v${shown?.version} (first version)`}
          </p>
          {restore && shown && shown.version !== liveVersion ? <RestoreButton {...restore} version={shown.version} /> : null}
        </div>
        <pre className="overflow-x-auto rounded-lg border border-border bg-black/20 py-2 font-mono text-[12px] leading-relaxed">
          {lines.map((line, i) => (
            <div
              key={i}
              className={cn(
                "px-3 whitespace-pre-wrap",
                line.kind === "added" && "bg-success/10 text-success",
                line.kind === "removed" && "bg-danger/10 text-danger line-through decoration-danger/40",
                line.kind === "same" && "text-muted-foreground",
              )}
            >
              <span className="mr-3 inline-block w-3 text-faint select-none">{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span>
              {line.text}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

function RestoreButton({ projectId, playbookId, version }: { projectId: string; playbookId: string; version: number }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} className="h-7 gap-1.5 text-[12px]">
        <History className="size-3.5" /> Restore v{version}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>Restore v{version}?</DialogTitle>
            <DialogDescription>Its content and embedding become a new version, so this rollback can itself be undone. Agents receive it from their next recall.</DialogDescription>
          </DialogHeader>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (kept in the version history)" maxLength={500} />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={pending}
              className="min-w-24"
              onClick={() =>
                startTransition(async () => {
                  const result = await rollbackPlaybook(projectId, playbookId, version, note);
                  if (result.ok) {
                    toast.success(`Restored v${version} as v${result.version}`);
                    setOpen(false);
                    router.refresh();
                  } else toast.error(result.error);
                })
              }
            >
              {pending ? <Loader2 className="size-4 animate-spin" /> : "Restore"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
