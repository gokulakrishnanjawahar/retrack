import { FlaskConical, ShieldX } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { OutcomeIconStatic, Pill, SectionCard } from "@/components/badges";
import { CodeBlock } from "@/components/code-block";
import { KpiCard } from "@/components/overview/kpi-card";
import { AssertionChips } from "@/components/regression/assertions";
import { PassRateChart } from "@/components/regression/pass-rate-chart";
import { RelativeTime } from "@/components/relative-time";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getProject, listAgents, listEvalCases, listTestRuns } from "@/lib/data";

export const metadata: Metadata = { title: "Regression" };

export default async function RegressionPage({ params }: PageProps<"/p/[projectId]/regression">) {
  const { projectId } = await params;
  await getProject(projectId);
  const [cases, runs, agents] = await Promise.all([listEvalCases(projectId), listTestRuns(projectId), listAgents(projectId)]);
  const testRuns = runs.filter((r) => !r.migrationId);
  const last = testRuns[0];
  const criticalFailing = cases.filter((c) => c.critical && c.last_result === "failed").length;
  const fromPlaybooks = cases.filter((c) => c.source === "playbook").length;
  const agentName = Object.values(agents)[0] ?? "support-agent";

  return (
    <PageBody>
      <PageHeader
        title="Regression"
        description="Every active playbook and recurring failure becomes a test case automatically. Run them in CI before you ship a prompt, tool or model change."
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard index={0} label="Active cases" value={cases.length} footnote={`${fromPlaybooks} from playbooks · ${cases.length - fromPlaybooks} from failures`} />
        <KpiCard index={1} label="Last pass rate" value={last ? (last.passed / Math.max(1, last.total)) * 100 : null} format="percent" footnote={last ? `${last.passed} of ${last.total} on ${last.model ?? "unknown model"}` : "No test run yet"} />
        <KpiCard index={2} label="Critical cases failing" value={criticalFailing} goodWhenUp={false} footnote="Failures that passed before block CI" />
        <KpiCard index={3} label="Test runs" value={testRuns.length} footnote={last ? <>Last <RelativeTime iso={last.at} /></> : undefined} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <SectionCard title="Pass rate by test run">
          <div className="px-2 pt-3 pb-2">
            {testRuns.length ? <PassRateChart runs={testRuns} /> : <p className="px-3 py-12 text-center text-[12.5px] text-faint">Run retrack test to see results here.</p>}
          </div>
        </SectionCard>
        <SectionCard title="Run in CI">
          <div className="p-4">
            <CodeBlock
              snippets={[
                { label: "CLI", language: "shell", code: `retrack test --entry my_agent:run_task --agent ${agentName} --threshold 0.9` },
                {
                  label: "GitHub Actions",
                  language: "shell",
                  code: `- uses: <owner>/<retrack-action-repo>@v1\n  env:\n    RETRACK_API_KEY: \${{ secrets.RETRACK_API_KEY }}\n  with:\n    entry: my_agent:run_task\n    agent: ${agentName}\n    threshold: "0.9"`,
                },
              ]}
            />
            <p className="pt-3 text-[11.5px] text-faint">Exit code 1 fails the build when a critical case regresses or the pass rate drops below the threshold.</p>
          </div>
        </SectionCard>
      </div>

      <SectionCard title={`Cases · ${cases.length}`} className="mt-4">
        {cases.length === 0 ? (
          <p className="px-5 py-10 text-center text-[12.5px] text-faint">Cases appear when playbooks become active or a failure repeats.</p>
        ) : (
          <ul className="divide-y divide-border">
            {cases.map((c) => (
              <li key={c.id} className="grid items-center gap-3 px-5 py-3 md:grid-cols-[24px_1.3fr_1fr_120px_110px]">
                <span className="text-faint">{c.source === "playbook" ? <FlaskConical className="size-4" /> : <ShieldX className="size-4" />}</span>
                <div className="min-w-0">
                  <p className="truncate text-[13px]">{c.input.task ?? "–"}</p>
                  <p className="font-mono text-[11px] text-faint">
                    {c.source === "playbook" ? (
                      <Link href={`/p/${projectId}/memory/${c.source_id}`} className="hover:text-foreground">
                        playbook
                      </Link>
                    ) : (
                      "failure signature"
                    )}{" "}
                    · {agents[c.agent_id] ?? "agent"}
                  </p>
                </div>
                <AssertionChips assertions={c.expected_assertions} />
                <div className="flex items-center gap-2">
                  {c.critical ? <Pill tone="danger">critical</Pill> : null}
                </div>
                <div className="flex items-center justify-end gap-2 text-[11.5px] text-faint">
                  {c.last_result ? <OutcomeIconStatic outcome={c.last_result === "passed" ? "success" : "failure"} /> : null}
                  {c.last_run_at ? <RelativeTime iso={c.last_run_at} /> : "not run"}
                </div>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </PageBody>
  );
}
