import { ArrowLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { OutcomeBadge, Pill, SectionCard } from "@/components/badges";
import { RelativeTime } from "@/components/relative-time";
import { StepTimeline } from "@/components/runs/step-timeline";
import { PageBody } from "@/components/shell/page-header";
import { getRun, listAgents } from "@/lib/data";

export const metadata: Metadata = { title: "Run" };

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-[11px] text-faint">{label}</p>
      <div className="text-[13px]">{children}</div>
    </div>
  );
}

export default async function RunPage({ params }: PageProps<"/p/[projectId]/runs/[runId]">) {
  const { projectId, runId } = await params;
  const [run, agents] = await Promise.all([getRun(projectId, runId), listAgents(projectId)]);
  const tokens = run.tokens_in + run.tokens_out;
  const usedIds = run.recall?.playbook_ids.length ? run.recall.playbook_ids : run.recalled_playbook_ids;

  return (
    <PageBody>
      <Link href={`/p/${projectId}/runs`} className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3.5" /> Runs
      </Link>
      <header className="space-y-3 pt-4 pb-8">
        <div className="flex flex-wrap items-center gap-2">
          <OutcomeBadge outcome={run.outcome} quarantined={run.taint_level === "quarantined"} />
          {run.outcome_source ? (
            <Pill>
              verified by {run.outcome_source}
              {run.confidence !== null ? ` · ${Math.round(run.confidence * 100)}%` : ""}
            </Pill>
          ) : null}
          <Pill tone={run.taint_level === "trusted" ? "success" : run.taint_level === "quarantined" ? "warning" : "neutral"}>
            {run.taint_level} input
          </Pill>
          {run.holdout ? <Pill>holdout: no memory</Pill> : null}
          {run.replay_of ? <Pill tone="brand">plan replay</Pill> : null}
        </div>
        <h1 className="text-gradient max-w-4xl text-2xl font-semibold tracking-tight">{run.task_text}</h1>
        <p className="font-mono text-[11.5px] text-faint">{run.id}</p>
      </header>

      <div className="surface grid grid-cols-2 gap-5 rounded-xl p-5 md:grid-cols-6">
        <Meta label="Agent">{agents[run.agent_id] ?? run.agent_id.slice(0, 8)}</Meta>
        <Meta label="Model">
          <span className="font-mono text-[12.5px]">{run.model_id}</span>
        </Meta>
        <Meta label="Tokens">
          <span className="tabular">{tokens.toLocaleString("en-US")}</span>
        </Meta>
        <Meta label="Cost">{run.cost_usd !== null ? `$${Number(run.cost_usd).toFixed(4)}` : "–"}</Meta>
        <Meta label="Duration">{run.latency_ms !== null ? `${(run.latency_ms / 1000).toFixed(2)} s` : "–"}</Meta>
        <Meta label="Captured">
          <RelativeTime iso={run.created_at} />
        </Meta>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_360px]">
        <SectionCard title={`Steps · ${run.steps.length}`}>
          <StepTimeline steps={run.steps} />
        </SectionCard>
        <div className="space-y-4">
          <SectionCard title="Memory used">
            <div className="space-y-3 p-5">
              {run.recall ? (
                <p className="font-mono text-[11.5px] text-faint">
                  {run.recall.mode} recall{run.recall.latency_ms !== null ? ` · ${run.recall.latency_ms} ms` : ""}
                  {run.recall.warning_ids.length ? ` · ${run.recall.warning_ids.length} warning(s)` : ""}
                </p>
              ) : (
                <p className="text-[12.5px] text-faint">This run did not ask for memory.</p>
              )}
              {usedIds.map((id) => (
                <Link key={id} href={`/p/${projectId}/memory/${id}`} className="block rounded-lg border border-border px-3 py-2 text-[12.5px] transition-colors hover:border-brand/40 hover:bg-brand-soft">
                  {run.playbookTitles[id] ?? id.slice(0, 8)}
                </Link>
              ))}
            </div>
          </SectionCard>
          <SectionCard title="Outcome signals">
            <ul className="divide-y divide-border">
              {run.signals.length === 0 ? <li className="px-5 py-4 text-[12.5px] text-faint">No signals yet.</li> : null}
              {run.signals.map((signal, i) => (
                <li key={i} className="flex items-center justify-between gap-3 px-5 py-2.5 text-[12.5px]">
                  <span className="font-mono text-muted-foreground">{signal.source}</span>
                  <OutcomeBadge outcome={signal.outcome} />
                  <span className="tabular font-mono text-[11px] text-faint">{Math.round(signal.confidence * 100)}%</span>
                </li>
              ))}
            </ul>
          </SectionCard>
          {run.findings.length ? (
            <SectionCard title="Firewall findings">
              <ul className="divide-y divide-border">
                {run.findings.map((f) => (
                  <li key={f.id} className="space-y-1 px-5 py-3">
                    <div className="flex items-center gap-2">
                      <Pill tone={f.severity === "block" ? "danger" : "warning"}>{f.severity}</Pill>
                      <span className="font-mono text-[11.5px] text-muted-foreground">{f.check_name}</span>
                    </div>
                    <p className="text-[12.5px] text-muted-foreground">{f.detail}</p>
                  </li>
                ))}
              </ul>
            </SectionCard>
          ) : null}
        </div>
      </div>

      {run.output_text ? (
        <SectionCard title="Final answer" className="mt-4">
          <p className="px-5 py-4 text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground">{run.output_text}</p>
        </SectionCard>
      ) : null}
    </PageBody>
  );
}
