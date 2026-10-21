import type { Metadata } from "next";
import { MemoryBoard } from "@/components/memory/memory-board";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getProject, getRole, listAgents, listFailureSignatures, listPlaybooks } from "@/lib/data";

export const metadata: Metadata = { title: "Memory" };

export default async function MemoryPage({ params }: PageProps<"/p/[projectId]/memory">) {
  const { projectId } = await params;
  await getProject(projectId);
  const [playbooks, failures, agents, role] = await Promise.all([
    listPlaybooks(projectId),
    listFailureSignatures(projectId),
    listAgents(projectId),
    getRole(projectId),
  ]);
  return (
    <PageBody>
      <PageHeader
        title="Memory"
        description="Playbooks distilled from verified successes, and failure signatures from repeated tool errors. Candidates become active after three trusted successes or your approval."
      />
      <MemoryBoard projectId={projectId} playbooks={playbooks} failures={failures} agents={agents} canManage={role === "owner" || role === "admin"} />
    </PageBody>
  );
}
