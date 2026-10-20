import type { MigrationCounts } from "@/lib/data";

// How a replayed case can end on the new model (server/src/retrack_server/migrations.py).
export const RESULTS = [
  { key: "passes", label: "Passes", color: "var(--success)", blocking: false },
  { key: "fixed", label: "Fixed", color: "oklch(0.78 0.12 190)", blocking: false },
  { key: "needs_relearning", label: "Needs relearning", color: "var(--warning)", blocking: false },
  { key: "breaks", label: "Breaks", color: "var(--danger)", blocking: true },
  { key: "returns", label: "Failure returns", color: "oklch(0.62 0.2 15)", blocking: true },
] as const;

export function blockingCount(counts: MigrationCounts) {
  return (counts.breaks ?? 0) + (counts.returns ?? 0);
}
