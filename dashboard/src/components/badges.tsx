import { CheckCircle2, CircleDashed, ShieldAlert, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const PILL = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10.5px] ring-1 whitespace-nowrap";

const PLAYBOOK: Record<string, string> = {
  active: "bg-success/10 text-success ring-success/25",
  candidate: "bg-brand-soft text-brand ring-brand/25",
  quarantined: "bg-warning/10 text-warning ring-warning/25",
  retired: "bg-white/[0.04] text-faint ring-border",
};

export function PlaybookStatusBadge({ status, className }: { status: string; className?: string }) {
  return <span className={cn(PILL, PLAYBOOK[status] ?? PLAYBOOK.retired, className)}>{status}</span>;
}

export function OutcomeBadge({ outcome, quarantined, className }: { outcome: string; quarantined?: boolean; className?: string }) {
  if (quarantined) {
    return (
      <span className={cn(PILL, PLAYBOOK.quarantined, className)}>
        <ShieldAlert className="size-3" /> quarantined
      </span>
    );
  }
  if (outcome === "success") {
    return (
      <span className={cn(PILL, "bg-success/10 text-success ring-success/25", className)}>
        <CheckCircle2 className="size-3" /> success
      </span>
    );
  }
  if (outcome === "failure") {
    return (
      <span className={cn(PILL, "bg-danger/10 text-danger ring-danger/25", className)}>
        <XCircle className="size-3" /> failure
      </span>
    );
  }
  return (
    <span className={cn(PILL, "bg-white/[0.04] text-muted-foreground ring-border", className)}>
      <CircleDashed className="size-3" /> unverified
    </span>
  );
}

export function OutcomeIconStatic({ outcome, quarantined }: { outcome: string; quarantined?: boolean }) {
  if (quarantined) return <ShieldAlert className="size-4 text-warning" />;
  if (outcome === "success") return <CheckCircle2 className="size-4 text-success" />;
  if (outcome === "failure") return <XCircle className="size-4 text-danger" />;
  return <CircleDashed className="size-4 text-faint" />;
}

export function Pill({ children, tone = "neutral", className }: { children: React.ReactNode; tone?: "neutral" | "brand" | "warning" | "danger" | "success"; className?: string }) {
  const tones = {
    neutral: "bg-white/[0.04] text-muted-foreground ring-border",
    brand: "bg-brand-soft text-brand ring-brand/25",
    warning: "bg-warning/10 text-warning ring-warning/25",
    danger: "bg-danger/10 text-danger ring-danger/25",
    success: "bg-success/10 text-success ring-success/25",
  };
  return <span className={cn(PILL, tones[tone], className)}>{children}</span>;
}

export function SectionCard({ title, action, children, className }: { title?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("surface rounded-xl", className)}>
      {title ? (
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
          <h2 className="text-[13.5px] font-medium">{title}</h2>
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}
