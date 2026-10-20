"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState, useTransition } from "react";
import { CodeBlock } from "@/components/code-block";
import { quickstartSnippets } from "@/lib/snippets";
import { FirstRunListener } from "@/components/project/first-run-listener";
import { SecretReveal } from "@/components/project/secret-reveal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createWorkspace } from "@/lib/actions";
import { cn } from "@/lib/utils";

const STEPS = ["Workspace", "Connect", "First run"];

export function OnboardingFlow({
  suggestedOrganization,
  apiUrl,
  hasProjects,
}: {
  suggestedOrganization: string;
  apiUrl: string;
  hasProjects: boolean;
}) {
  const [created, setCreated] = useState<{ projectId: string; secret: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const step = created ? 1 : 0;

  function submit(formData: FormData) {
    setError(null);
    startTransition(async () => {
      const result = await createWorkspace({
        organization: String(formData.get("organization") ?? ""),
        project: String(formData.get("project") ?? ""),
      });
      if (result.ok) setCreated({ projectId: result.projectId, secret: result.secret });
      else setError(result.error);
    });
  }

  return (
    <div className="space-y-10">
      <ol className="flex items-center gap-3">
        {STEPS.map((label, i) => (
          <li key={label} className="flex items-center gap-3">
            <span
              className={cn(
                "flex size-6 items-center justify-center rounded-full font-mono text-[11px] ring-1 transition-colors duration-500",
                i < step && "bg-success/15 text-success ring-success/30",
                i === step && "bg-brand-soft text-foreground ring-brand/40",
                i > step && "text-faint ring-border",
              )}
            >
              {i + 1}
            </span>
            <span className={cn("text-[13px]", i <= step ? "text-foreground" : "text-faint")}>{label}</span>
            {i < STEPS.length - 1 ? <span className="h-px w-8 bg-border" /> : null}
          </li>
        ))}
      </ol>

      <AnimatePresence mode="wait">
        {created ? (
          <motion.section
            key="connect"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="space-y-8"
          >
            <div className="space-y-2">
              <h1 className="text-gradient text-3xl font-semibold tracking-tight">Connect your agent</h1>
              <p className="text-sm text-muted-foreground">
                Here is your project&apos;s API key. Add the callback to your LangGraph agent and run it once.
              </p>
            </div>
            <SecretReveal secret={created.secret} />
            <CodeBlock snippets={quickstartSnippets(apiUrl, created.secret)} />
            <FirstRunListener projectId={created.projectId} />
            <div className="text-center">
              <Link href={`/p/${created.projectId}`} className="text-[13px] text-muted-foreground hover:text-foreground">
                Skip for now
              </Link>
            </div>
          </motion.section>
        ) : (
          <motion.section key="workspace" exit={{ opacity: 0, y: -12 }} className="space-y-8">
            <div className="space-y-2">
              <h1 className="text-gradient text-3xl font-semibold tracking-tight">
                {hasProjects ? "Create another project" : "Set up your workspace"}
              </h1>
              <p className="text-sm text-muted-foreground">
                A project holds one environment&apos;s runs and memory, isolated from every other project.
              </p>
            </div>
            <form action={submit} className="surface space-y-5 rounded-xl p-6">
              <div className="space-y-2">
                <Label htmlFor="organization">Organization</Label>
                <Input id="organization" name="organization" defaultValue={suggestedOrganization} placeholder="Acme" required maxLength={100} className="h-10" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="project">Project</Label>
                <Input id="project" name="project" defaultValue="production" required maxLength={100} className="h-10" />
                <p className="text-xs text-faint">Tip: one project per environment, such as production and staging.</p>
              </div>
              {error ? (
                <p role="alert" className="rounded-md border border-danger/25 bg-danger/10 px-3 py-2 text-[13px] text-danger">
                  {error}
                </p>
              ) : null}
              <Button type="submit" disabled={pending} className="group h-10 w-full">
                {pending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <>
                    Create workspace
                    <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                  </>
                )}
              </Button>
            </form>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  );
}
