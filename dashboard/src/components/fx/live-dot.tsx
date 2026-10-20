import { cn } from "@/lib/utils";

const TONES = {
  live: "bg-success",
  brand: "bg-brand",
  warning: "bg-warning",
  idle: "bg-faint",
} as const;

// A status dot; `pulse` adds an expanding ring for live states.
export function LiveDot({
  tone = "live",
  pulse = true,
  className,
}: {
  tone?: keyof typeof TONES;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("relative inline-flex size-2", className)}>
      {pulse && (
        <span className={cn("absolute inset-0 rounded-full animate-pulse-ring", TONES[tone])} />
      )}
      <span className={cn("relative inline-flex size-2 rounded-full", TONES[tone])} />
    </span>
  );
}
