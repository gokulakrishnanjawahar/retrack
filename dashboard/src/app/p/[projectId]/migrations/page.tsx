import { ArrowRight, Loader2 } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Pill, SectionCard } from "@/components/badges";
import { CodeBlock } from "@/components/code-block";
import { MigrationBar } from "@/components/regression/migration-bar";
import { blockingCount, RESULTS } from "@/lib/migration-results";
import { RelativeTime } from "@/components/relative-time";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getProject, listAgents, listMigrations } from "@/lib/data";

export const metadata: Metadata = { title: "Model migrations" };

export default async function MigrationsPage({ params }: PageProps<"/p/[projectId]/migrations">) {
  const { projectId } = await params;
  await getProject(projectId);
  const [reports, agents] = await Promise.all([listMigrations(projectId), listAgents(projectId)]);
  const agentName = Object.values(agents)[0] ?? "support-agent";
  return (
    <PageBody>
      <PageHeader
        title="Model migrations"
        description="Before you switch models, replay your memory on the new one. Playbooks that still pass are validated for it; anything that breaks is listed before your users see it."
      />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <div className="space-y-3">
          {reports.length === 0 ? (
            <p className="surface rounded-xl px-6 py-14 text-center text-sm text-muted-foreground">No migrations yet. Run retrack migrate to test a new model.</p>
          ) : (
            reports.map((r) => {
              const counts = r.summary?.counts ?? {};
              const blocked = blockingCount(counts);
              return (
                <Link key={r.id} href={`/p/${projectId}/migrations/${r.id}`} className="surface block space-y-4 rounded-xl p-5 transition-colors hover:ring-1 hover:ring-brand/30">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2.5 font-mono text-[13px]">
                      <span className="text-muted-foreground">{r.from_model ?? "current"}</span>
                      <ArrowRight className="size-3.5 text-faint" />
                      <span>{r.to_model}</span>
                    </div>
                    {r.status === "running" ? (
                      <Pill tone="brand">
                        <Loader2 className="size-3 animate-spin" /> running
                      </Pill>
                    ) : blocked ? (
                      <Pill tone="danger">not ready · {blocked} blocking</Pill>
                    ) : (
                      <Pill tone="success">ready to switch</Pill>
                    )}
                  </div>
                  <MigrationBar counts={counts} />
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px]">
                    {RESULTS.map((res) =>
                      counts[res.key] ? (
                        <span key={res.key} className="flex items-center gap-1.5 text-muted-foreground">
                          <span className="size-1.5 rounded-full" style={{ background: res.color }} />
                          {res.label} <span className="tabular text-foreground">{counts[res.key]}</span>
                        </span>
                      ) : null,
                    )}
                    <span className="ml-auto text-faint">
                      {agents[r.agent_id] ?? "agent"} · <RelativeTime iso={r.created_at} />
                    </span>
                  </div>
                  {!r.model_applied ? <p className="text-[11.5px] text-warning">The entry point did not take a model id, so the replay may not have used {r.to_model}.</p> : null}
                </Link>
              );
            })
          )}
        </div>
        <SectionCard title="Test a new model">
          <div className="space-y-3 p-4">
            <CodeBlock snippets={[{ label: "CLI", language: "shell", code: `retrack migrate --to claude-sonnet-5 \\\n  --entry my_agent:run_task --agent ${agentName}` }]} />
            <p className="text-[11.5px] leading-relaxed text-faint">
              Your entry point takes the model id as a third argument: <code className="font-mono">run_task(task, callbacks, model_id)</code>. Exit code 1 means something breaks or a known failure returns.
            </p>
          </div>
        </SectionCard>
      </div>
    </PageBody>
  );
}
