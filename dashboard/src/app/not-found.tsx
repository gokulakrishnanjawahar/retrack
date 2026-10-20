import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { Backdrop } from "@/components/fx/backdrop";

export default function NotFound() {
  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center gap-6 px-6 text-center">
      <Backdrop />
      <Logo />
      <p className="text-gradient font-mono text-6xl font-semibold tracking-tight">404</p>
      <p className="max-w-sm text-sm text-muted-foreground">This page does not exist, or you do not have access to it.</p>
      <Link href="/" className="rounded-lg bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground">
        Back to your dashboard
      </Link>
    </div>
  );
}
