import type { Metadata } from "next";
import Link from "next/link";
import { Pill, SectionCard } from "@/components/badges";
import { RelativeTime } from "@/components/relative-time";
import { ProposalQueue } from "@/components/review/proposal-queue";
import { ReviewQueue } from "@/components/review/review-queue";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getProject, getRole, listAgents, listOpenProposals, listOpenReviews, listQuarantinedRuns } from "@/lib/data";

export const metadata: Metadata = { title: "Review" };

export default async function ReviewPage({ params }: PageProps<"/p/[projectId]/review">) {
  const { projectId } = await params;
  await getProject(projectId);
  const [items, role, quarantined, proposals, agents] = await Promise.all([
    listOpenReviews(projectId),
    getRole(projectId),
    listQuarantinedRuns(projectId),
    listOpenProposals(projectId),
    listAgents(projectId),
  ]);
  const canManage = role === "owner" || role === "admin";
  return (
    <PageBody>
      <PageHeader
        title="Review"
        description="Memory waiting for a person: playbooks proposed across agents, and memory the firewall held back. Approving makes it active and records you as the reviewer."
      />
      <div className="space-y-8">
        <ProposalQueue projectId={projectId} proposals={proposals} agents={agents} canManage={canManage} />
        <section className="space-y-3">
          {proposals.length ? <h2 className="text-sm font-medium text-muted-foreground">Held back by the firewall · {items.length}</h2> : null}
          <ReviewQueue projectId={projectId} items={items} canManage={canManage} />
        </section>
      </div>
      <SectionCard title={`Quarantined runs · ${quarantined.length}`} className="mt-8">
        {quarantined.length === 0 ? (
          <p className="px-5 py-8 text-center text-[12.5px] text-faint">No runs have been quarantined.</p>
        ) : (
          <ul className="divide-y divide-border">
            {quarantined.map((run) => (
              <li key={run.id}>
                <Link href={`/p/${projectId}/runs/${run.id}`} className="grid gap-1.5 px-5 py-3 transition-colors hover:bg-white/[0.025] md:grid-cols-[1fr_auto] md:items-center">
                  <div className="min-w-0">
                    <p className="truncate text-[13px]">{run.task_text}</p>
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {run.findings.length ? (
                        run.findings.map((f) => (
                          <Pill key={f.id} tone={f.severity === "block" ? "danger" : "warning"}>
                            {f.check_name}
                          </Pill>
                        ))
                      ) : (
                        <Pill tone="warning">quarantined</Pill>
                      )}
                    </div>
                  </div>
                  <RelativeTime iso={run.created_at} className="text-[11.5px] text-faint" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </PageBody>
  );
}
