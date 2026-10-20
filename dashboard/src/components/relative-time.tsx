"use client";

import { useNow } from "@/hooks/use-now";
import { formatDate, timeAgo } from "@/lib/format";

export function RelativeTime({ iso, className }: { iso: string; className?: string }) {
  const now = useNow();
  return (
    <time dateTime={iso} title={`${formatDate(iso)} ${new Date(iso).toLocaleTimeString("en-GB")}`} className={className} suppressHydrationWarning>
      {timeAgo(iso, now)}
    </time>
  );
}
