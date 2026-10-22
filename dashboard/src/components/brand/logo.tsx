import { cn } from "@/lib/utils";

// The Retrack mark, "Return ring": a ring left open where a run comes back, around a solid
// core, the memory it returns to. Monochrome: it takes the text colour (currentColor).
export function LogoMark({ className, label }: { className?: string; label?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={cn("size-[22px] shrink-0", className)}
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      <path
        d="M19.73 9.93A8 8 0 1 1 16 5.07"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2.6" fill="currentColor" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-foreground", className)}>
      <LogoMark />
      <span className="text-[17px] leading-none font-semibold tracking-[-0.04em]">retrack</span>
    </span>
  );
}
