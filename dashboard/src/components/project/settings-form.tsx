"use client";

import { Loader2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, useTransition, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { updateProjectSettings } from "@/lib/actions";
import type { Project } from "@/lib/data";

function Row({ title, description, children }: { title: string; description: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-4 border-b border-border px-6 py-5 last:border-0 md:grid-cols-[1fr_1.1fr] md:gap-10">
      <div className="space-y-1">
        <p className="text-[13.5px] font-medium">{title}</p>
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">{description}</p>
      </div>
      <div className="flex items-start md:justify-end">{children}</div>
    </div>
  );
}

export function SettingsForm({ project, canManage }: { project: Project; canManage: boolean }) {
  const [tools, setTools] = useState(project.trustedTools);
  const [draft, setDraft] = useState("");
  const [taskTrusted, setTaskTrusted] = useState(project.taskTrusted);
  const [holdout, setHoldout] = useState(Math.round(project.holdoutRate * 100));
  const [retention, setRetention] = useState(project.retentionDays);
  const [rateLimit, setRateLimit] = useState(project.ingestRateLimit);
  const [pending, startTransition] = useTransition();

  function addTool() {
    const name = draft.trim();
    if (name && !tools.includes(name)) setTools([...tools, name].sort());
    setDraft("");
  }

  function save() {
    startTransition(async () => {
      const result = await updateProjectSettings(project.id, {
        trustedTools: draft.trim() ? [...tools, draft.trim()] : tools,
        taskTrusted,
        holdoutRate: holdout / 100,
        retentionDays: retention,
        ingestRateLimit: rateLimit,
      });
      if (result.ok) {
        setDraft("");
        toast.success("Settings saved");
      } else toast.error(result.error);
    });
  }

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Memory firewall</h2>
        <div className="surface rounded-xl">
          <Row
            title="Trusted tools"
            description="Results from these tools count as trusted input. Anything else is untrusted, and runs that used it need more evidence or a review before they become memory."
          >
            <div className="w-full max-w-sm space-y-2.5">
              <div className="flex flex-wrap gap-1.5">
                <AnimatePresence initial={false}>
                  {tools.map((tool) => (
                    <motion.span
                      key={tool}
                      layout
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.8 }}
                      className="inline-flex items-center gap-1 rounded-md bg-white/[0.05] py-1 pr-1 pl-2 font-mono text-[12px] ring-1 ring-border"
                    >
                      {tool}
                      {canManage ? (
                        <button
                          type="button"
                          aria-label={`Remove ${tool}`}
                          onClick={() => setTools(tools.filter((t) => t !== tool))}
                          className="rounded p-0.5 text-faint hover:bg-white/10 hover:text-foreground"
                        >
                          <X className="size-3" />
                        </button>
                      ) : null}
                    </motion.span>
                  ))}
                </AnimatePresence>
                {tools.length === 0 ? <span className="text-[12.5px] text-faint">No trusted tools: every result is untrusted.</span> : null}
              </div>
              {canManage ? (
                <Input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault();
                      addTool();
                    }
                  }}
                  placeholder="Add a tool name and press Enter"
                  className="font-mono text-[12.5px]"
                />
              ) : null}
            </div>
          </Row>
          <Row
            title="Trust task text"
            description="Turn on only if task text never comes from end users or outside content."
          >
            <Switch checked={taskTrusted} onCheckedChange={setTaskTrusted} disabled={!canManage} />
          </Row>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Measurement and limits</h2>
        <div className="surface rounded-xl">
          <Row
            title="Holdout"
            description="Share of tasks that run without memory, so Retrack can prove the difference memory makes."
          >
            <NumberField value={holdout} onChange={setHoldout} min={0} max={50} suffix="%" disabled={!canManage} />
          </Row>
          <Row title="Retention" description="Runs older than this are deleted, except runs that support live memory.">
            <NumberField value={retention} onChange={setRetention} min={1} max={3650} suffix="days" disabled={!canManage} />
          </Row>
          <Row title="Ingest rate limit" description="Runs accepted per minute. Above it, the API answers 429 and the SDK retries.">
            <NumberField value={rateLimit} onChange={setRateLimit} min={1} max={100000} suffix="/ min" disabled={!canManage} />
          </Row>
        </div>
      </section>

      {canManage ? (
        <div className="flex justify-end">
          <Button onClick={save} disabled={pending} className="h-9 min-w-28">
            {pending ? <Loader2 className="size-4 animate-spin" /> : "Save changes"}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-faint">Only owners and admins can change settings.</p>
      )}
    </div>
  );
}

function NumberField({
  value,
  onChange,
  min,
  max,
  suffix,
  disabled,
}: {
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  suffix: string;
  disabled: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <Input
        type="number"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(e) => onChange(Math.min(max, Math.max(min, Number(e.target.value) || min)))}
        className="tabular w-28 text-right"
      />
      <span className="w-10 text-[12.5px] text-faint">{suffix}</span>
    </div>
  );
}
