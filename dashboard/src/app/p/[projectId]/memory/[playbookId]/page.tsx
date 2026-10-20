import { ArrowLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Pill, PlaybookStatusBadge, SectionCard } from "@/components/badges";
import { PlaybookActions } from "@/components/memory/playbook-actions";
import { VersionHistory } from "@/components/memory/version-history";
import { RelativeTime } from "@/components/relative-time";
import { PageBody } from "@/components/shell/page-header";
import { getPlaybook, getRole, listAgents } from "@/lib/data";
import { stepText } from "@/lib/diff";

export const metadata: Metadata = { title: "Playbook" };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-medium tracking-wide text-faint uppercase">{label}</p>
      <div className="text-[13px] leading-relaxed text-muted-foreground">{children}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="tabular text-xl font-semibold">{value}</p>
      <p className="text-[11px] text-faint">{label}</p>
    </div>
  );
}

export default async function PlaybookPage({ params }: PageProps<"/p/[projectId]/memory/[playbookId]">) {
  const { projectId, playbookId } = await params;
  const [pb, role, agents] = await Promise.all([getPlaybook(projectId, playbookId), getRole(projectId), listAgents(projectId)]);
  const canManage = role === "owner" || role === "admin";
  const sources = pb.provenance?.source_run_ids ?? [];

  return (
    <PageBody>
      <Link href={`/p/${projectId}/memory`} className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3.5" /> Memory
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4 pt-4 pb-8">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <PlaybookStatusBadge status={pb.status} />
            <span className="font-mono text-[11.5px] text-faint">
              {agents[pb.agent_id] ?? "agent"} · v{pb.version}
            </span>
          </div>
          <h1 className="text-gradient max-w-3xl text-2xl font-semibold tracking-tight">{pb.title}</h1>
          {pb.approved_by ? <p className="text-[12px] text-faint">Approved by {pb.approved_by}</p> : null}
        </div>
        {canManage ? (
          <div className="flex gap-2">
            <PlaybookActions projectId={projectId} playbookId={pb.id} status={pb.status} />
          </div>
        ) : null}
      </header>

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <SectionCard title="Playbook">
          <div className="space-y-6 p-5">
            {pb.task_pattern ? <Field label="When to use">{pb.task_pattern}</Field> : null}
            {pb.preconditions ? <Field label="Preconditions">{pb.preconditions}</Field> : null}
            <Field label="Steps">
              <ol className="space-y-2">
                {(pb.steps as unknown[]).map((step, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-brand-soft font-mono text-[10.5px] text-brand ring-1 ring-brand/25">{i + 1}</span>
                    <span className="text-foreground/90">{stepText(step)}</span>
                  </li>
                ))}
                {(pb.steps as unknown[]).length === 0 ? <li className="text-faint">No steps recorded.</li> : null}
              </ol>
            </Field>
            {pb.pitfalls ? <Field label="Pitfalls">{pb.pitfalls}</Field> : null}
            {Object.keys(pb.tool_versions ?? {}).length ? (
              <Field label="Tool versions">
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(pb.tool_versions).map(([tool, version]) => (
                    <Pill key={tool}>
                      {tool} {version}
                    </Pill>
                  ))}
                </div>
              </Field>
            ) : null}
          </div>
        </SectionCard>

        <div className="space-y-4">
          <SectionCard title="Performance">
            <div className="grid grid-cols-3 gap-3 p-5">
              <Stat label="uses" value={pb.uses} />
              <Stat label="success" value={pb.uses ? `${Math.round(pb.success_rate * 100)}%` : "–"} />
              <Stat label="confidence" value={`${Math.round(pb.confidence * 100)}%`} />
            </div>
            <div className="border-t border-border px-5 py-3 text-[12px] text-faint">
              {pb.last_success_at ? (
                <>
                  Last success <RelativeTime iso={pb.last_success_at} />
                </>
              ) : (
                "No recorded success after recall yet"
              )}
            </div>
          </SectionCard>
          <SectionCard title="Evidence">
            <div className="space-y-3 p-5 text-[12.5px]">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Trusted successes</span>
                <span className="tabular">{pb.trusted_support}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Untrusted sources</span>
                <span className="tabular">{pb.untrusted_sources}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Quarantined sources</span>
                <span className={`tabular ${pb.quarantined_sources ? "text-warning" : ""}`}>{pb.quarantined_sources}</span>
              </div>
              {sources.length ? (
                <div className="space-y-1.5 border-t border-border pt-3">
                  <p className="text-[11px] text-faint">Source runs</p>
                  <div className="flex flex-wrap gap-1.5">
                    {sources.slice(0, 12).map((id) => (
                      <Link key={id} href={`/p/${projectId}/runs/${id}`} className="rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground ring-1 ring-border hover:text-foreground">
                        {id.slice(0, 8)}
                      </Link>
                    ))}
                  </div>
                </div>
              ) : null}
              {pb.validated_models.length ? (
                <div className="space-y-1.5 border-t border-border pt-3">
                  <p className="text-[11px] text-faint">Validated on</p>
                  <div className="flex flex-wrap gap-1.5">
                    {pb.validated_models.map((m) => (
                      <Pill key={m} tone="success">
                        {m}
                      </Pill>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </SectionCard>
          <SectionCard title="Regression case">
            <div className="p-5 text-[12.5px]">
              {pb.evalCase ? (
                <div className="flex items-center justify-between">
                  <Pill tone={pb.evalCase.last_result === "passed" ? "success" : pb.evalCase.last_result === "failed" ? "danger" : "neutral"}>
                    {pb.evalCase.last_result ?? "not run yet"}
                  </Pill>
                  <span className="font-mono text-[11px] text-faint">{pb.evalCase.last_model_id ?? pb.evalCase.status}</span>
                </div>
              ) : (
                <p className="text-faint">Created when the playbook becomes active.</p>
              )}
            </div>
          </SectionCard>
          {pb.findings.length ? (
            <SectionCard title="Firewall findings">
              <ul className="divide-y divide-border">
                {pb.findings.map((f) => (
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

      {pb.versions.length ? (
        <SectionCard title="Version history" className="mt-4">
          <VersionHistory versions={pb.versions} />
        </SectionCard>
      ) : null}
    </PageBody>
  );
}
