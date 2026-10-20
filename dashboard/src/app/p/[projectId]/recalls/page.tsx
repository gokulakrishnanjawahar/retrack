import type { Metadata } from "next";
import Link from "next/link";
import { OutcomeIconStatic, Pill } from "@/components/badges";
import { KpiCard } from "@/components/overview/kpi-card";
import { RelativeTime } from "@/components/relative-time";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getProject, listAgents, listRecalls } from "@/lib/data";

export const metadata: Metadata = { title: "Recalls" };

const MODE_TONE = { hybrid: "brand", keyword: "neutral", holdout: "warning", no_agent: "neutral" } as const;

export default async function RecallsPage({ params }: PageProps<"/p/[projectId]/recalls">) {
  const { projectId } = await params;
  await getProject(projectId);
  const [{ recalls, titles, outcomes, tasks }, agents] = await Promise.all([listRecalls(projectId), listAgents(projectId)]);
  const served = recalls.filter((r) => !r.holdout);
  const hits = served.filter((r) => r.playbook_ids.length > 0).length;
  const latencies = recalls.map((r) => r.latency_ms).filter((v): v is number => v !== null).sort((a, b) => a - b);
  const p50 = latencies.length ? latencies[Math.floor(latencies.length / 2)] : null;
  const p95 = latencies.length ? latencies[Math.min(latencies.length - 1, Math.floor(latencies.length * 0.95))] : null;

  return (
    <PageBody>
      <PageHeader title="Recalls" description="What memory each task received before it ran: the 100 most recent recalls." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard index={0} label="Recalls shown" value={recalls.length} />
        <KpiCard index={1} label="Found memory" value={served.length ? (hits / served.length) * 100 : null} format="percent" footnote={`${hits} of ${served.length} non-holdout recalls`} />
        <KpiCard index={2} label="Latency p50" value={p50} format="ms" footnote={p95 !== null ? `p95 ${p95} ms, server side` : undefined} />
        <KpiCard index={3} label="Holdout" value={recalls.length - served.length} footnote="tasks that ran without memory" />
      </div>
      <div className="surface mt-4 overflow-hidden rounded-xl">
        {recalls.length === 0 ? (
          <p className="px-6 py-14 text-center text-sm text-muted-foreground">No recalls yet. Call rt.recall(task) before your agent runs.</p>
        ) : (
          <ul className="divide-y divide-border">
            {recalls.map((r) => {
              const row = (
                <div className="grid grid-cols-[20px_1fr_auto] items-center gap-3 px-5 py-3 md:grid-cols-[20px_1fr_1.1fr_90px_80px_90px]">
                  {r.run_id && outcomes[r.run_id] ? <OutcomeIconStatic outcome={outcomes[r.run_id]} /> : <span className="size-4" />}
                  <div className="min-w-0">
                    <p className="truncate text-[13px]">{(r.run_id && tasks[r.run_id]) || <span className="text-faint">run not captured</span>}</p>
                    <p className="truncate font-mono text-[11px] text-faint">{agents[r.agent_id] ?? "agent"}</p>
                  </div>
                  <div className="hidden min-w-0 flex-wrap gap-1.5 md:flex">
                    {r.playbook_ids.length ? (
                      r.playbook_ids.map((id) => (
                        <Pill key={id} tone="brand" className="max-w-[240px]">
                          <span className="truncate">{titles[id] ?? id.slice(0, 8)}</span>
                        </Pill>
                      ))
                    ) : (
                      <span className="font-mono text-[10.5px] text-faint">{r.holdout ? "withheld (holdout)" : "no match above threshold"}</span>
                    )}
                    {r.warning_ids.length ? <Pill tone="danger">{r.warning_ids.length} warning{r.warning_ids.length === 1 ? "" : "s"}</Pill> : null}
                  </div>
                  <div className="hidden md:block">
                    <Pill tone={MODE_TONE[r.mode]}>{r.mode}</Pill>
                  </div>
                  <p className="tabular hidden text-right font-mono text-[11.5px] text-muted-foreground md:block">{r.latency_ms !== null ? `${r.latency_ms} ms` : "–"}</p>
                  <RelativeTime iso={r.created_at} className="text-right text-[11.5px] text-faint" />
                </div>
              );
              return (
                <li key={r.id}>
                  {r.run_id && tasks[r.run_id] ? (
                    <Link href={`/p/${projectId}/runs/${r.run_id}`} className="block transition-colors hover:bg-white/[0.025]">
                      {row}
                    </Link>
                  ) : (
                    row
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </PageBody>
  );
}
