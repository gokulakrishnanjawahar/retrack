"use client";

import { KeyRound, Loader2, Plus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, useTransition } from "react";
import { toast } from "sonner";
import { LiveDot } from "@/components/fx/live-dot";
import { SecretReveal } from "@/components/project/secret-reveal";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useNow } from "@/hooks/use-now";
import { createApiKey, revokeApiKey } from "@/lib/actions";
import type { ApiKey } from "@/lib/data";
import { formatDate, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const RECENT_MS = 5 * 60 * 1000;

export function KeysManager({ projectId, keys, canManage }: { projectId: string; keys: ApiKey[]; canManage: boolean }) {
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const now = useNow();
  const active = keys.filter((k) => !k.revokedAt);
  const revoked = keys.filter((k) => k.revokedAt);

  return (
    <>
      <PageHeader
        title="API keys"
        description="Keys let your agents send runs and recall memory for this project. Only a hash is stored: a key is shown once, when you create it."
        actions={
          canManage ? (
            <Button onClick={() => setCreating(true)} className="h-9 gap-1.5">
              <Plus className="size-4" /> Create key
            </Button>
          ) : null
        }
      />

      <div className="surface overflow-hidden rounded-xl">
        <div className="grid grid-cols-[1.4fr_1.6fr_1fr_1fr_auto] gap-4 border-b border-border px-5 py-2.5 text-[11px] font-medium tracking-wide text-faint uppercase max-md:hidden">
          <span>Name</span>
          <span>Key</span>
          <span>Created</span>
          <span>Last used</span>
          <span className="w-16" />
        </div>
        {keys.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <KeyRound className="size-6 text-faint" />
            <p className="text-sm text-muted-foreground">No keys yet.</p>
          </div>
        ) : null}
        <ul>
          <AnimatePresence initial={false}>
            {[...active, ...revoked].map((key, i) => (
              <motion.li
                key={key.id}
                layout
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0, transition: { delay: i * 0.03 } }}
                exit={{ opacity: 0 }}
                className={cn(
                  "grid grid-cols-[1.4fr_1.6fr_1fr_1fr_auto] items-center gap-4 border-b border-border px-5 py-3.5 last:border-0 max-md:grid-cols-1 max-md:gap-1.5",
                  key.revokedAt && "opacity-50",
                )}
              >
                <span className="flex items-center gap-2 text-[13.5px] font-medium">
                  {key.name}
                  {key.revokedAt ? (
                    <span className="rounded-full px-1.5 py-px font-mono text-[10px] text-faint ring-1 ring-border">revoked</span>
                  ) : null}
                </span>
                <code className="font-mono text-[12.5px] text-muted-foreground">
                  {key.prefix}
                  <span className="text-faint">••••••••</span>
                </code>
                <span className="text-[13px] text-muted-foreground">{formatDate(key.createdAt)}</span>
                <span className="flex items-center gap-2 text-[13px] text-muted-foreground" suppressHydrationWarning>
                  {key.lastUsedAt ? (
                    <>
                      {now - new Date(key.lastUsedAt).getTime() < RECENT_MS ? <LiveDot /> : null}
                      {timeAgo(key.lastUsedAt, now)}
                    </>
                  ) : (
                    <span className="text-faint">Never</span>
                  )}
                </span>
                <span className="w-16 text-right">
                  {canManage && !key.revokedAt ? (
                    <button
                      type="button"
                      onClick={() => setRevoking(key)}
                      className="text-[12.5px] text-muted-foreground transition-colors hover:text-danger"
                    >
                      Revoke
                    </button>
                  ) : null}
                </span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      </div>
      {!canManage ? (
        <p className="pt-4 text-xs text-faint">Only owners and admins can create or revoke keys.</p>
      ) : null}

      <CreateKeyDialog projectId={projectId} open={creating} onOpenChange={setCreating} />
      <RevokeDialog projectId={projectId} apiKey={revoking} onClose={() => setRevoking(null)} />
    </>
  );
}

function CreateKeyDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [env, setEnv] = useState<"live" | "test">("live");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function close(next: boolean) {
    onOpenChange(next);
    if (!next) {
      setTimeout(() => {
        setSecret(null);
        setError(null);
        setEnv("live");
      }, 200);
    }
  }

  function submit(formData: FormData) {
    setError(null);
    startTransition(async () => {
      const result = await createApiKey(projectId, { name: String(formData.get("name") ?? ""), env });
      if (result.ok) setSecret(result.secret);
      else setError(result.error);
    });
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-[460px]">
        {secret ? (
          <>
            <DialogHeader>
              <DialogTitle>Your new API key</DialogTitle>
              <DialogDescription>Store it in your agent&apos;s environment as RETRACK_API_KEY.</DialogDescription>
            </DialogHeader>
            <SecretReveal secret={secret} />
            <DialogFooter>
              <Button onClick={() => close(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form action={submit} className="space-y-5">
            <DialogHeader>
              <DialogTitle>Create API key</DialogTitle>
              <DialogDescription>Name it after where it will be used, such as “ci” or “prod-agent”.</DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="key-name">Name</Label>
              <Input id="key-name" name="name" placeholder="prod-agent" maxLength={100} autoFocus />
            </div>
            <div className="space-y-2">
              <Label>Environment</Label>
              <div className="grid grid-cols-2 gap-2">
                {(["live", "test"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setEnv(value)}
                    className={cn(
                      "rounded-lg border px-3 py-2.5 text-left transition-colors",
                      env === value ? "border-brand/50 bg-brand-soft" : "border-border hover:bg-white/[0.03]",
                    )}
                  >
                    <span className="block font-mono text-[12px]">rtk_{value}_…</span>
                    <span className="block text-[11.5px] text-faint">{value === "live" ? "Production agents" : "CI and local testing"}</span>
                  </button>
                ))}
              </div>
            </div>
            {error ? <p className="text-[13px] text-danger">{error}</p> : null}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending} className="min-w-24">
                {pending ? <Loader2 className="size-4 animate-spin" /> : "Create key"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function RevokeDialog({ projectId, apiKey, onClose }: { projectId: string; apiKey: ApiKey | null; onClose: () => void }) {
  const [pending, startTransition] = useTransition();
  return (
    <Dialog open={apiKey !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Revoke “{apiKey?.name}”?</DialogTitle>
          <DialogDescription>
            Agents using <code className="font-mono">{apiKey?.prefix}…</code> stop working immediately. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={pending}
            onClick={() =>
              startTransition(async () => {
                if (!apiKey) return;
                const result = await revokeApiKey(projectId, apiKey.id);
                if (result.ok) {
                  toast.success(`Revoked ${apiKey.name}`);
                  onClose();
                } else {
                  toast.error(result.error);
                }
              })
            }
          >
            {pending ? <Loader2 className="size-4 animate-spin" /> : "Revoke key"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
