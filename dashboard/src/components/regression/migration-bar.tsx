"use client";

import { motion } from "motion/react";
import type { MigrationCounts } from "@/lib/data";
import { RESULTS } from "@/lib/migration-results";

export function MigrationBar({ counts }: { counts: MigrationCounts }) {
  const total = RESULTS.reduce((acc, r) => acc + (counts[r.key] ?? 0), 0);
  return (
    <div className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-white/[0.05]">
      {total
        ? RESULTS.map((r, i) =>
            counts[r.key] ? (
              <motion.div
                key={r.key}
                style={{ background: r.color }}
                className="h-full"
                initial={{ width: 0 }}
                animate={{ width: `${((counts[r.key] ?? 0) / total) * 100}%` }}
                transition={{ delay: 0.1 + i * 0.07, duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
              />
            ) : null,
          )
        : null}
    </div>
  );
}
