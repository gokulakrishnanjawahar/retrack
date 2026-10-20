import type { Metadata } from "next";
import { SettingsForm } from "@/components/project/settings-form";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { getProject, getRole } from "@/lib/data";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage({ params }: PageProps<"/p/[projectId]/settings">) {
  const { projectId } = await params;
  const [project, role] = await Promise.all([getProject(projectId), getRole(projectId)]);
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
    </PageBody>
  );
}
