import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { OutcomeIconStatic, Pill } from "@/components/badges";
import { RunFilters } from "@/components/runs/run-filters";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { RelativeTime } from "@/components/relative-time";
import { getProject, listAgents, listRuns, RUNS_PAGE } from "@/lib/data";

export const metadata: Metadata = { title: "Runs" };

export default async function RunsPage({ params, searchParams }: PageProps<"/p/[projectId]/runs">) {
  const [{ projectId }, sp] = await Promise.all([params, searchParams]);
  const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);
  const filters = { outcome: one(sp.outcome), q: one(sp.q), agent: one(sp.agent), before: one(sp.before) };
  await getProject(projectId);
  const [runs, agents] = await Promise.all([listRuns(projectId, filters), listAgents(projectId)]);
  const older = runs.length === RUNS_PAGE ? runs[runs.length - 1].created_at : null;
  const keep = new URLSearchParams(Object.entries({ ...filters, before: older ?? "" }).filter(([, v]) => v) as [string, string][]);

  return (
    <PageBody>
      <PageHeader title="Runs" description="Every captured run, with its verified outcome and the memory it used." />
      <Suspense>
        <RunFilters agents={agents} />
      </Suspense>
      <div className="surface mt-4 overflow-hidden rounded-xl">
        {runs.length === 0 ? (
          <p className="px-6 py-14 text-center text-sm text-muted-foreground">No runs match these filters.</p>
        ) : (
          <ul className="divide-y divide-border">
            {runs.map((run) => (
              <li key={run.id}>
                <Link
                  href={`/p/${projectId}/runs/${run.id}`}
                  className="grid grid-cols-[20px_1fr_auto] items-center gap-3 px-5 py-3 transition-colors hover:bg-white/[0.025] md:grid-cols-[20px_1fr_130px_110px_100px]"
                >
                  <OutcomeIconStatic outcome={run.outcome} quarantined={run.taint_level === "quarantined"} />
                  <div className="min-w-0">
                    <p className="truncate text-[13px]">{run.task_text}</p>
                    <p className="truncate font-mono text-[11px] text-faint">
                      {agents[run.agent_id] ?? run.agent_id.slice(0, 8)} · {run.model_id}
                      {run.outcome_source ? ` · verified by ${run.outcome_source}` : ""}
                    </p>
                  </div>
                  <div className="hidden md:block">
                    {run.holdout ? (
                      <Pill>holdout</Pill>
                    ) : run.recalled_playbook_ids.length ? (
                      <Pill tone="brand">
                        {run.recalled_playbook_ids.length} playbook{run.recalled_playbook_ids.length === 1 ? "" : "s"}
                      </Pill>
                    ) : (
                      <span className="font-mono text-[10.5px] text-faint">no memory</span>
                    )}
                  </div>
                  <p className="tabular hidden text-right font-mono text-[11.5px] text-muted-foreground md:block">
                    {(run.tokens_in + run.tokens_out).toLocaleString("en-US")} tok
                  </p>
                  <RelativeTime iso={run.created_at} className="text-right text-[11.5px] text-faint" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      {older ? (
        <div className="flex justify-center pt-5">
          <Link href={`/p/${projectId}/runs?${keep}`} className="rounded-lg border border-border px-3 py-1.5 text-[12.5px] text-muted-foreground hover:bg-white/[0.04] hover:text-foreground">
            Older runs
          </Link>
        </div>
      ) : null}
    </PageBody>
  );
}
