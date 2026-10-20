"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LiveDot } from "@/components/fx/live-dot";

// Re-renders the page's server data on an interval, so the numbers stay current.
export function AutoRefresh({ seconds = 30 }: { seconds?: number }) {
  const router = useRouter();
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    const id = setInterval(() => {
      setLeft((n) => {
        if (n <= 1) {
          router.refresh();
          return seconds;
        }
        return n - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [router, seconds]);
  return (
    <span className="inline-flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
      <LiveDot /> live · refresh in {left}s
    </span>
  );
}
