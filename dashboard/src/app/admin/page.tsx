import { ArrowLeft, Download } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/admin/auto-refresh";
import { RunsArea } from "@/components/admin/runs-area";
import { Pill, SectionCard } from "@/components/badges";
import { Logo } from "@/components/brand/logo";
import { Backdrop } from "@/components/fx/backdrop";
import { KpiCard } from "@/components/overview/kpi-card";
import { RelativeTime } from "@/components/relative-time";
import { getAdminOverview, getAdminProjectStats, getUser } from "@/lib/data";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Admin" };

function compact(n: number) {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

const RANGES = [7, 30, 90] as const;

function pct(value: number | null) {
  return value === null ? "–" : `${(value * 100).toFixed(1)}%`;
}

export default async function AdminPage({ searchParams }: PageProps<"/admin">) {
  const sp = await searchParams;
  const days = RANGES.find((d) => String(d) === sp.days) ?? 30;
  const [user, o, projects] = await Promise.all([getUser(), getAdminOverview(), getAdminProjectStats(days)]);
  const unhealthy = o.cron.filter((c) => c.active && c.status && c.status !== "succeeded");
  return (
    <div className="relative min-h-dvh">
      <Backdrop className="opacity-70" />
      <header className="flex items-center justify-between border-b border-border px-6 py-4 md:px-10">
        <div className="flex items-center gap-4">
          <Logo />
          <Pill tone="brand">super admin</Pill>
        </div>
        <div className="flex items-center gap-5">
          <AutoRefresh />
          <span className="hidden text-xs text-faint md:inline">{user.email}</span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1180px] px-6 py-10 md:px-10">
        <Link href="/" className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> Dashboard
        </Link>
        <div className="pt-4 pb-8">
          <h1 className="text-gradient text-[26px] font-semibold tracking-tight">Retrack, across all projects</h1>
          <p className="text-sm text-muted-foreground">Only accounts in super_admins can open this page.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <KpiCard index={0} label="Users" value={o.users} footnote={`${o.users_7d} new this week`} />
          <KpiCard index={1} label="Organizations" value={o.organizations} footnote={`${o.projects} projects`} />
          <KpiCard index={2} label="Runs · 7 days" value={o.runs_7d} spark={o.daily.slice(-14).map((d) => d.runs)} footnote={`${compact(o.runs_total)} all time`} />
          <KpiCard index={3} label="Success rate · 30 days" value={o.success_rate_30d === null ? null : o.success_rate_30d * 100} format="percent" footnote="Runs with a verified outcome, all projects" />
          <KpiCard index={4} label="Agent spend · 30 days" value={o.agent_cost_30d} format="usd" footnote="What customers' agents reported spending" />
          <KpiCard index={5} label="Active playbooks" value={o.playbooks_active} footnote={`${o.reviews_open} reviews open`} />
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <SectionCard title="Runs per day · all projects">
            <div className="px-2 pt-3 pb-2">
              <RunsArea daily={o.daily} />
            </div>
          </SectionCard>
          <SectionCard title="Workers and queue" action={unhealthy.length ? <Pill tone="danger">{unhealthy.length} failing</Pill> : <Pill tone="success">healthy</Pill>}>
            <div className="grid grid-cols-2 gap-3 border-b border-border p-5">
              <div>
                <p className="tabular text-xl font-semibold">{o.queue_depth}</p>
                <p className="text-[11px] text-faint">runs waiting in queue</p>
              </div>
              <div>
                <p className={`tabular text-xl font-semibold ${o.dead_letters ? "text-danger" : ""}`}>{o.dead_letters}</p>
                <p className="text-[11px] text-faint">dead letters</p>
              </div>
            </div>
            <ul className="divide-y divide-border">
              {o.cron.map((job) => (
                <li key={job.job} className="flex items-center gap-3 px-5 py-3 text-[12.5px]">
                  <span className={`size-2 rounded-full ${!job.active ? "bg-faint" : job.status === "succeeded" ? "bg-success" : job.status ? "bg-danger" : "bg-faint"}`} />
                  <span className="font-mono">{job.job}</span>
                  <span className="font-mono text-[11px] text-faint">{job.schedule}</span>
                  <span className="ml-auto text-[11.5px] text-faint">
                    {!job.active ? "paused" : job.last_run ? <RelativeTime iso={job.last_run} /> : "never run"}
                  </span>
                </li>
              ))}
            </ul>
          </SectionCard>
        </div>

        <div className="mt-4 grid gap-4">
          <SectionCard title="Usage · 30 days">
            <div className="grid grid-cols-2 gap-5 p-5">
              <div>
                <p className="tabular text-xl font-semibold">{compact(o.usage_30d.runs)}</p>
                <p className="text-[11px] text-faint">runs captured</p>
              </div>
              <div>
                <p className="tabular text-xl font-semibold">{compact(o.usage_30d.recalls)}</p>
                <p className="text-[11px] text-faint">recalls served</p>
              </div>
              <div>
                <p className="tabular text-xl font-semibold">{compact(o.usage_30d.llm_input_tokens)}</p>
                <p className="text-[11px] text-faint">Retrack LLM input tokens</p>
              </div>
              <div>
                <p className="tabular text-xl font-semibold">{compact(o.usage_30d.llm_output_tokens)}</p>
                <p className="text-[11px] text-faint">Retrack LLM output tokens</p>
              </div>
            </div>
          </SectionCard>
        </div>
        <SectionCard
          title={`Projects · last ${days} days`}
          className="mt-4"
          action={
            <div className="flex items-center gap-2">
              <div className="flex rounded-lg border border-border p-0.5">
                {RANGES.map((d) => (
                  <Link
                    key={d}
                    href={`/admin?days=${d}`}
                    className={cn("rounded-md px-2 py-0.5 font-mono text-[11px]", d === days ? "bg-white/[0.08] text-foreground" : "text-muted-foreground hover:text-foreground")}
                  >
                    {d}d
                  </Link>
                ))}
              </div>
              <a href={`/admin/export?days=${days}`} className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-2.5 py-1 text-[12px] font-medium text-primary-foreground">
                <Download className="size-3.5" /> Export CSV
              </a>
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-[12.5px]">
              <thead>
                <tr className="border-b border-border text-left text-[11px] font-medium tracking-wide text-faint uppercase">
                  <th className="px-5 py-2.5 font-medium">Project</th>
                  <th className="px-3 py-2.5 text-right font-medium">Runs</th>
                  <th className="px-3 py-2.5 text-right font-medium">Success</th>
                  <th className="px-3 py-2.5 text-right font-medium">Memory lift</th>
                  <th className="px-3 py-2.5 text-right font-medium">Recall hits</th>
                  <th className="px-3 py-2.5 text-right font-medium">Agent cost</th>
                  <th className="px-3 py-2.5 text-right font-medium">Retrack LLM tokens</th>
                  <th className="px-3 py-2.5 text-right font-medium">Playbooks</th>
                  <th className="px-5 py-2.5 text-right font-medium">Last run</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {projects.map((p) => (
                  <tr key={p.project_id} className="transition-colors hover:bg-white/[0.02]">
                    <td className="px-5 py-3">
                      <span className="block truncate">{p.project}</span>
                      <span className="block truncate text-[11px] text-faint">
                        {p.organization} · {p.members} member{p.members === 1 ? "" : "s"}
                      </span>
                    </td>
                    <td className="tabular px-3 py-3 text-right font-mono">{p.runs.toLocaleString("en-US")}</td>
                    <td className="tabular px-3 py-3 text-right font-mono">{pct(p.success_rate)}</td>
                    <td className={cn("tabular px-3 py-3 text-right font-mono", p.lift_points !== null && p.lift_points < 0 && "text-danger")}>
                      {p.lift_points === null ? "–" : `${p.lift_points >= 0 ? "+" : ""}${p.lift_points.toFixed(1)}`}
                      {p.lift_points !== null && p.holdout_known < 20 ? <span className="text-faint">*</span> : null}
                    </td>
                    <td className="tabular px-3 py-3 text-right font-mono">{pct(p.recall_hit_rate)}</td>
                    <td className="tabular px-3 py-3 text-right font-mono">${p.agent_cost_usd.toFixed(2)}</td>
                    <td className="tabular px-3 py-3 text-right font-mono">{compact(p.llm_input_tokens + p.llm_output_tokens)}</td>
                    <td className="tabular px-3 py-3 text-right font-mono">
                      {p.playbooks_active}
                      {p.open_reviews ? <span className="text-warning"> · {p.open_reviews} to review</span> : null}
                    </td>
                    <td className="px-5 py-3 text-right text-faint">{p.last_run_at ? <RelativeTime iso={p.last_run_at} /> : "never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border px-5 py-2.5 text-[11px] text-faint">* fewer than 20 holdout runs with a known outcome, so the lift is not yet reliable. The CSV has every column, including token counts and failure signatures.</p>
        </SectionCard>
      </main>
    </div>
  );
}
