import type { Metadata } from "next";
import { Logo } from "@/components/brand/logo";
import { Backdrop } from "@/components/fx/backdrop";
import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";
import { getUser, listProjects } from "@/lib/data";

export const metadata: Metadata = { title: "Set up" };

export default async function OnboardingPage() {
  const [user, projects] = await Promise.all([getUser(), listProjects()]);
  const domain = user.email.split("@")[1]?.split(".")[0] ?? "";
  const suggested = domain && !["gmail", "outlook", "yahoo", "icloud", "hotmail", "proton"].includes(domain)
    ? domain.charAt(0).toUpperCase() + domain.slice(1)
    : "";
  return (
    <div className="relative min-h-dvh">
      <Backdrop />
      <header className="flex items-center justify-between px-6 py-5">
        <Logo />
        <span className="text-xs text-faint">{user.email}</span>
      </header>
      <main className="mx-auto w-full max-w-[640px] px-6 pt-10 pb-24">
        <OnboardingFlow
          suggestedOrganization={suggested}
          apiUrl={process.env.NEXT_PUBLIC_RETRACK_API_URL ?? ""}
          hasProjects={projects.length > 0}
        />
      </main>
    </div>
  );
}
