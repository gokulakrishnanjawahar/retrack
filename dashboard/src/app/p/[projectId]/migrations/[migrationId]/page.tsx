import { ArrowLeft, ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Pill, SectionCard } from "@/components/badges";
import { KpiCard } from "@/components/overview/kpi-card";
import { MigrationBar } from "@/components/regression/migration-bar";
import { blockingCount, RESULTS } from "@/lib/migration-results";
import { RelativeTime } from "@/components/relative-time";
import { PageBody } from "@/components/shell/page-header";
import { getMigration } from "@/lib/data";

export const metadata: Metadata = { title: "Migration report" };

const TONE = { passes: "success", fixed: "success", needs_relearning: "warning", breaks: "danger", returns: "danger" } as const;

export default async function MigrationPage({ params }: PageProps<"/p/[projectId]/migrations/[migrationId]">) {
  const { projectId, migrationId } = await params;
  const report = await getMigration(projectId, migrationId);
  const counts = report.summary?.counts ?? {};
  const items = report.summary?.items ?? [];
  const order: string[] = ["breaks", "returns", "needs_relearning", "fixed", "passes"];
  const sorted = [...items].sort((a, b) => order.indexOf(a.result) - order.indexOf(b.result));
  const blocked = blockingCount(counts);

  return (
    <PageBody>
      <Link href={`/p/${projectId}/migrations`} className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3.5" /> Model migrations
      </Link>
      <header className="space-y-3 pt-4 pb-8">
        <div className="flex items-center gap-3 font-mono text-xl">
          <span className="text-muted-foreground">{report.from_model ?? "current"}</span>
          <ArrowRight className="size-4 text-faint" />
          <span className="text-gradient font-semibold">{report.to_model}</span>
        </div>
        <div className="flex items-center gap-2">
          {report.status === "running" ? <Pill tone="brand">running</Pill> : blocked ? <Pill tone="danger">not ready · {blocked} blocking</Pill> : <Pill tone="success">ready to switch</Pill>}
          <span className="text-[12px] text-faint">
            Started <RelativeTime iso={report.created_at} />
          </span>
        </div>
      </header>
      <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-5">
        {RESULTS.map((r, i) => (
          <KpiCard key={r.key} index={i} label={r.label} value={counts[r.key] ?? 0} />
        ))}
      </div>
      <div className="mt-4">
        <MigrationBar counts={counts} />
      </div>
      <SectionCard title={`Replayed cases · ${items.length}`} className="mt-4">
        <ul className="divide-y divide-border">
          {sorted.map((item) => (
            <li key={item.case_id} className="grid gap-2 px-5 py-3 md:grid-cols-[150px_1fr]">
              <div>
                <Pill tone={TONE[item.result]}>{item.result.replace("_", " ")}</Pill>
              </div>
              <div className="min-w-0 space-y-1">
                {item.source === "playbook" ? (
                  <Link href={`/p/${projectId}/memory/${item.source_id}`} className="text-[13px] hover:underline">
                    {item.title}
                  </Link>
                ) : (
                  <p className="font-mono text-[12.5px]">{item.title}</p>
                )}
                {item.failures.map((f, i) => (
                  <p key={i} className="font-mono text-[11.5px] text-danger/90">
                    {f}
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </SectionCard>
    </PageBody>
  );
}
