import { cn } from "@/lib/utils";

// Ambient page background: a soft violet glow, a fading hairline grid and film grain.
export function Backdrop({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none fixed inset-0 -z-10 overflow-hidden", className)}>
      <div className="absolute -top-[30%] left-1/2 h-[70vh] w-[90vw] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,oklch(0.55_0.2_285/22%),transparent)] blur-2xl" />
      <div className="absolute top-[10%] -right-[10%] h-[45vh] w-[40vw] rounded-full bg-[radial-gradient(closest-side,oklch(0.6_0.14_190/10%),transparent)] blur-2xl" />
      <div className="bg-grid absolute inset-0" />
      <div className="bg-noise absolute inset-0" />
    </div>
  );
}
