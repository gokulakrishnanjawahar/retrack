import type { Metadata } from "next";
import { CodeBlock, quickstartSnippets } from "@/components/code-block";
import { LiveDot } from "@/components/fx/live-dot";
import { KpiCard } from "@/components/overview/kpi-card";
import { LiveRunFeed } from "@/components/overview/live-run-feed";
import { MemoryCard } from "@/components/overview/memory-card";
import { RoiCard } from "@/components/overview/roi-card";
import { RunsChart } from "@/components/overview/runs-chart";
import { FirstRunListener } from "@/components/project/first-run-listener";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getOverview, getProject, listAgents, listRecentRuns, listTopPlaybooks } from "@/lib/data";
import { change } from "@/lib/metrics";

export const metadata: Metadata = { title: "Overview" };

function signed(value: number, digits = 0) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export default async function OverviewPage({ params }: PageProps<"/p/[projectId]">) {
  const { projectId } = await params;
  const [project, overview, runs, agents, top] = await Promise.all([
    getProject(projectId),
    getOverview(projectId),
    listRecentRuns(projectId),
    listAgents(projectId),
    listTopPlaybooks(projectId),
  ]);

  if (runs.length === 0) {
    return (
      <PageBody>
        <PageHeader
          title={`Connect ${project.name}`}
          description="No runs yet. Attach the callback to your agent and the first run appears here live."
        />
        <div className="grid max-w-3xl gap-6">
          <CodeBlock snippets={quickstartSnippets(process.env.NEXT_PUBLIC_RETRACK_API_URL ?? "")} />
          <FirstRunListener projectId={project.id} />
        </div>
      </PageBody>
    );
  }

  const { kpis, daily } = overview;
  const runsDelta = change(kpis.runs_7d, kpis.runs_prev_7d);
  const rateDelta =
    kpis.success_rate_7d !== null && kpis.success_rate_prev_7d !== null
      ? (kpis.success_rate_7d - kpis.success_rate_prev_7d) * 100
      : null;
  const last14 = daily.slice(-14);

  return (
    <PageBody>
      <PageHeader
        title="Overview"
        description={
          <span className="inline-flex items-center gap-2">
            <LiveDot /> {project.organization} / {project.name} · last 30 days
          </span>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          index={0}
          label="Runs · 7 days"
          value={kpis.runs_7d}
          delta={runsDelta}
          deltaLabel={runsDelta === null ? undefined : `${signed(runsDelta * 100)}%`}
          spark={last14.map((d) => d.runs)}
        />
        <KpiCard
          index={1}
          label="Success rate · 7 days"
          value={kpis.success_rate_7d === null ? null : kpis.success_rate_7d * 100}
          format="percent"
          delta={rateDelta}
          deltaLabel={rateDelta === null ? undefined : `${signed(rateDelta, 1)} pts`}
          spark={last14.map((d) => (d.successes + d.failures ? (d.successes / (d.successes + d.failures)) * 100 : 0))}
        />
        <KpiCard
          index={2}
          label="Active playbooks"
          value={kpis.playbooks.active ?? 0}
          footnote={`${kpis.playbooks.candidate ?? 0} candidates gathering evidence · ${kpis.recalls_7d.toLocaleString("en-US")} recalls this week`}
        />
        <KpiCard
          index={3}
          label="Blocked by firewall · 7 days"
          value={kpis.quarantined_7d}
          goodWhenUp={false}
          footnote={kpis.open_reviews ? `${kpis.open_reviews} waiting for your review` : "Nothing waiting for review"}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <RoiCard overview={overview} holdoutRate={project.holdoutRate} />
        <div className="surface rounded-xl p-5 pb-3">
          <div className="flex items-center justify-between">
            <p className="text-[12.5px] text-muted-foreground">Runs per day</p>
            <p className="text-[11.5px] text-faint">{(kpis.tokens_7d / 1000).toFixed(1)}k tokens this week</p>
          </div>
          <RunsChart daily={daily} />
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_300px]">
        <LiveRunFeed projectId={project.id} initialRuns={runs} agents={agents} />
        <MemoryCard kpis={kpis} top={top} />
      </div>
    </PageBody>
  );
}
