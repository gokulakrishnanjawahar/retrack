import { redirect } from "next/navigation";
import { listProjects } from "@/lib/data";

// Signed-in home: the first project, or onboarding when there is none yet.
export default async function Home() {
  const projects = await listProjects();
  redirect(projects.length ? `/p/${projects[0].id}` : "/onboarding");
}
