import type { Metadata } from "next";
import { KeysManager } from "@/components/project/keys-manager";
import { PageBody } from "@/components/shell/page-header";
import { getRole, listKeys } from "@/lib/data";

export const metadata: Metadata = { title: "API keys" };

export default async function KeysPage({ params }: PageProps<"/p/[projectId]/keys">) {
  const { projectId } = await params;
  const [keys, role] = await Promise.all([listKeys(projectId), getRole(projectId)]);
  return (
    <PageBody>
      <KeysManager projectId={projectId} keys={keys} canManage={role === "owner" || role === "admin"} />
    </PageBody>
  );
}
