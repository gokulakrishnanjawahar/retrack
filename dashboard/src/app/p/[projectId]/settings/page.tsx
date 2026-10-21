import type { Metadata } from "next";
import { SectionCard } from "@/components/badges";
import { SettingsForm } from "@/components/project/settings-form";
import { UsageChart } from "@/components/project/usage-chart";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getProject, getRole, listUsage } from "@/lib/data";

function compact(n: number) {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage({ params }: PageProps<"/p/[projectId]/settings">) {
  const { projectId } = await params;
  const [project, role, usage] = await Promise.all([getProject(projectId), getRole(projectId), listUsage(projectId)]);
  const total = (key: keyof (typeof usage)[number]) => usage.reduce((acc, d) => acc + Number(d[key] ?? 0), 0);
  return (
    <PageBody>
      <PageHeader
        title="Settings"
        description={
          <>
            {project.organization} / <span className="text-foreground">{project.name}</span>
            <span className="ml-2 font-mono text-xs text-faint">{project.id}</span>
          </>
        }
      />
      <SettingsForm project={project} canManage={role === "owner" || role === "admin"} />
      <SectionCard title="Usage · last 30 days" className="mt-8">
        <div className="grid grid-cols-2 gap-5 border-b border-border p-5 md:grid-cols-5">
          {(
            [
              ["runs_captured", "runs captured"],
              ["recalls_served", "recalls served"],
              ["distillations", "distillations"],
              ["tokens_processed", "agent tokens seen"],
              ["llm_input_tokens", "Retrack LLM tokens in"],
            ] as const
          ).map(([key, label]) => (
            <div key={key}>
              <p className="tabular text-xl font-semibold">{compact(total(key))}</p>
              <p className="text-[11px] text-faint">{label}</p>
            </div>
          ))}
        </div>
        <div className="px-3 pt-3 pb-2">
          {usage.length ? <UsageChart usage={usage} /> : <p className="py-8 text-center text-[12.5px] text-faint">No usage yet.</p>}
        </div>
      </SectionCard>
    </PageBody>
  );
}
