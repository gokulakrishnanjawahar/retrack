"use client";

import { Search } from "lucide-react";
import { motion } from "motion/react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { cn } from "@/lib/utils";

const OUTCOMES = [
  ["", "All"],
  ["success", "Succeeded"],
  ["failure", "Failed"],
  ["unknown", "Unverified"],
  ["quarantined", "Quarantined"],
] as const;

export function RunFilters({ agents }: { agents: Record<string, string> }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [pending, startTransition] = useTransition();
  const outcome = params.get("outcome") ?? "";
  const agent = params.get("agent") ?? "";

  function update(next: Record<string, string>) {
    const sp = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(next)) {
      if (value) sp.set(key, value);
      else sp.delete(key);
    }
    sp.delete("before");
    startTransition(() => router.replace(`${pathname}${sp.size ? `?${sp}` : ""}`));
  }

  useEffect(() => {
    if (q === (params.get("q") ?? "")) return;
    const id = setTimeout(() => update({ q }), 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  return (
    <div className={cn("flex flex-wrap items-center gap-3 transition-opacity", pending && "opacity-70")}>
      <div className="relative flex rounded-lg border border-border bg-white/[0.02] p-0.5">
        {OUTCOMES.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => update({ outcome: value })}
            className={cn(
              "relative z-10 rounded-md px-2.5 py-1 text-[12.5px] transition-colors",
              outcome === value ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {outcome === value ? (
              <motion.span layoutId="run-filter" className="absolute inset-0 -z-10 rounded-md bg-white/[0.07] ring-1 ring-white/10" transition={{ type: "spring", stiffness: 500, damping: 38 }} />
            ) : null}
            {label}
          </button>
        ))}
      </div>
      <select
        value={agent}
        onChange={(e) => update({ agent: e.target.value })}
        className="h-8 rounded-lg border border-border bg-white/[0.02] px-2.5 text-[12.5px] text-muted-foreground outline-none focus:border-brand/50"
      >
        <option value="">All agents</option>
        {Object.entries(agents).map(([id, name]) => (
          <option key={id} value={id}>
            {name}
          </option>
        ))}
      </select>
      <div className="relative ml-auto w-full max-w-xs">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search task text"
          className="h-8 w-full rounded-lg border border-border bg-white/[0.02] pr-3 pl-8 text-[12.5px] outline-none placeholder:text-faint focus:border-brand/50"
        />
      </div>
    </div>
  );
}
