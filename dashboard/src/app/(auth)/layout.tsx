import { PipelineShowcase } from "@/components/auth/pipeline-showcase";
import { Logo } from "@/components/brand/logo";
import { Backdrop } from "@/components/fx/backdrop";
import { TAGLINE } from "@/lib/brand";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <Backdrop />
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-border p-10 lg:flex">
        <Logo />
        <div className="space-y-8">
          <div className="max-w-[520px] space-y-4">
            <h1 className="text-gradient text-[44px] leading-[1.05] font-semibold tracking-[-0.03em]">
              {TAGLINE}
            </h1>
            <p className="text-[15px] leading-relaxed text-muted-foreground">
              Retrack captures every run, verifies the outcome, turns successes into playbooks and
              failures into warnings, and recalls them before the next task. A firewall keeps
              untrusted runs out of memory.
            </p>
          </div>
          <PipelineShowcase />
        </div>
        <p className="text-xs text-faint">Data stays in your project, isolated by row-level security.</p>
      </section>
      <main className="flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-[380px]">
          <div className="mb-10 space-y-3 lg:hidden">
            <Logo />
            <p className="text-sm text-muted-foreground">{TAGLINE}</p>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
