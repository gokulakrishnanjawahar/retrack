"use client";

import { motion } from "motion/react";
import { useState } from "react";
import type { PlaybookDetail } from "@/lib/data";
import { diffLines, snapshotText } from "@/lib/diff";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export function VersionHistory({ versions }: { versions: PlaybookDetail["versions"] }) {
  const [selected, setSelected] = useState(versions[0]?.version ?? 1);
  const index = versions.findIndex((v) => v.version === selected);
  const current = versions[index];
  const previous = versions[index + 1];
  const lines = current ? diffLines(previous ? snapshotText(previous.snapshot) : "", snapshotText(current.snapshot)) : [];

  return (
    <div className="grid md:grid-cols-[200px_1fr]">
      <ol className="border-b border-border p-2 md:border-r md:border-b-0">
        {versions.map((v) => (
          <li key={v.version}>
            <button
              type="button"
              onClick={() => setSelected(v.version)}
              className={cn("relative w-full rounded-md px-3 py-2 text-left transition-colors", v.version === selected ? "text-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              {v.version === selected ? <motion.span layoutId="version" className="absolute inset-0 rounded-md bg-white/[0.06] ring-1 ring-white/[0.06]" /> : null}
              <span className="relative block font-mono text-[12.5px]">v{v.version}</span>
              <span className="relative block truncate text-[11px] text-faint">
                {v.change_reason} · {formatDate(v.created_at)}
              </span>
            </button>
          </li>
        ))}
      </ol>
      <div className="min-w-0 p-4">
        <p className="pb-2 text-[11.5px] text-faint">
          {previous ? `Changes from v${previous.version} to v${current?.version}` : `v${current?.version} (first version)`}
        </p>
        <pre className="overflow-x-auto rounded-lg border border-border bg-black/20 py-2 font-mono text-[12px] leading-relaxed">
          {lines.map((line, i) => (
            <div
              key={i}
              className={cn(
                "px-3 whitespace-pre-wrap",
                line.kind === "added" && "bg-success/10 text-success",
                line.kind === "removed" && "bg-danger/10 text-danger line-through decoration-danger/40",
                line.kind === "same" && "text-muted-foreground",
              )}
            >
              <span className="mr-3 inline-block w-3 text-faint select-none">{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span>
              {line.text}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
