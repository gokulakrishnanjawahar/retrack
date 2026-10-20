import { cn } from "@/lib/utils";

// The Retrack mark: a loop that closes back on itself (runs feeding memory feeding runs),
// with a node where memory is recalled. Its gradient is defined once in LogoDefs, because a
// copy inside a hidden element (the sidebar on phones) would not render for the others.
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden className={cn("size-7", className)}>
      <rect x="1" y="1" width="30" height="30" rx="8" fill="oklch(1 0 0 / 4%)" />
      <rect x="1.5" y="1.5" width="29" height="29" rx="7.5" stroke="oklch(1 0 0 / 12%)" />
      <path
        d="M10.5 21.5V12.8a3.3 3.3 0 0 1 3.3-3.3h3.9a3.6 3.6 0 0 1 0 7.2h-3.4l5.2 4.8"
        stroke="url(#rt-g)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="21.6" cy="21.6" r="1.9" fill="oklch(0.86 0.12 175)" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">Retrack</span>
    </span>
  );
}

export function LogoDefs() {
  return (
    <svg width="0" height="0" aria-hidden className="absolute">
      <defs>
        <linearGradient id="rt-g" x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
          <stop stopColor="oklch(0.82 0.13 285)" />
          <stop offset="0.55" stopColor="oklch(0.74 0.15 250)" />
          <stop offset="1" stopColor="oklch(0.82 0.13 175)" />
        </linearGradient>
      </defs>
    </svg>
  );
}
