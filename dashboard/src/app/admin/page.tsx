import { ArrowLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/admin/auto-refresh";
import { RunsArea } from "@/components/admin/runs-area";
import { Pill, SectionCard } from "@/components/badges";
import { Logo } from "@/components/brand/logo";
import { Backdrop } from "@/components/fx/backdrop";
import { KpiCard } from "@/components/overview/kpi-card";
import { RelativeTime } from "@/components/relative-time";
import { getAdminOverview, getUser } from "@/lib/data";

export const metadata: Metadata = { title: "Admin" };

function compact(n: number) {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export default async function AdminPage() {
  const [user, o] = await Promise.all([getUser(), getAdminOverview()]);
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

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard index={0} label="Users" value={o.users} footnote={`${o.users_7d} new this week`} />
          <KpiCard index={1} label="Organizations · projects" value={o.organizations} footnote={`${o.projects} projects`} />
          <KpiCard index={2} label="Runs · 7 days" value={o.runs_7d} spark={o.daily.slice(-14).map((d) => d.runs)} footnote={`${compact(o.runs_total)} all time`} />
          <KpiCard index={3} label="Active playbooks" value={o.playbooks_active} footnote={`${o.reviews_open} reviews open`} />
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

        <div className="mt-4 grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <SectionCard title="Most active projects · 7 days">
            <ul className="divide-y divide-border">
              {o.top_projects.map((p, i) => {
                const max = Math.max(1, ...o.top_projects.map((t) => t.runs_7d));
                return (
                  <li key={p.id} className="grid grid-cols-[24px_1fr_1fr_70px] items-center gap-3 px-5 py-3 text-[12.5px]">
                    <span className="font-mono text-faint">{i + 1}</span>
                    <span className="truncate">
                      {p.project} <span className="text-faint">· {p.organization}</span>
                    </span>
                    <div className="h-1 overflow-hidden rounded-full bg-white/[0.05]">
                      <div className="h-full rounded-full bg-brand/80" style={{ width: `${(p.runs_7d / max) * 100}%` }} />
                    </div>
                    <span className="tabular text-right font-mono">{p.runs_7d.toLocaleString("en-US")}</span>
                  </li>
                );
              })}
            </ul>
          </SectionCard>
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
      </main>
    </div>
  );
}
