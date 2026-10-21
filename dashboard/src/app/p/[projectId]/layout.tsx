import { Logo } from "@/components/brand/logo";
import { Backdrop } from "@/components/fx/backdrop";
import { ProjectSwitcher } from "@/components/shell/project-switcher";
import { MobileNav, SidebarNav } from "@/components/shell/sidebar-nav";
import { UserMenu } from "@/components/shell/user-menu";
import { countOpenProposals, countOpenReviews, getProject, getRole, getUser, isSuperAdmin, listProjects } from "@/lib/data";

export default async function ProjectLayout({ children, params }: LayoutProps<"/p/[projectId]">) {
  const { projectId } = await params;
  const [user, project, projects, role, superAdmin, reviews, proposals] = await Promise.all([
    getUser(),
    getProject(projectId),
    listProjects(),
    getRole(projectId),
    isSuperAdmin(),
    countOpenReviews(projectId),
    countOpenProposals(projectId),
  ]);
  const openReviews = reviews + proposals;

  return (
    <div className="relative flex min-h-dvh">
      <Backdrop className="opacity-60" />
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar/80 backdrop-blur-xl md:flex">
        <div className="px-4 pt-4 pb-3">
          <Logo />
        </div>
        <div className="px-3 pb-4">
          <ProjectSwitcher current={project} projects={projects} />
        </div>
        <div className="flex-1 overflow-y-auto px-3">
          <SidebarNav projectId={project.id} superAdmin={superAdmin} openReviews={openReviews} />
        </div>
        <div className="border-t border-sidebar-border p-3">
          <UserMenu email={user.email} role={role} />
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between border-b border-border px-4 py-3 md:hidden">
          <Logo />
          <span className="truncate text-xs text-faint">{project.name}</span>
        </div>
        <MobileNav projectId={project.id} superAdmin={superAdmin} openReviews={openReviews} />
        {children}
      </div>
    </div>
  );
}
