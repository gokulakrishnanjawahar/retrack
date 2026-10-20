"use client";

type Entry = { name?: string | number; value?: number | string | null; color?: string };

export function ChartTooltip({
  active,
  payload,
  label,
  unit = "",
}: {
  active?: boolean;
  payload?: Entry[];
  label?: string | number;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-popover/95 px-3 py-2 shadow-xl backdrop-blur">
      <p className="pb-1 font-mono text-[11px] text-faint">{formatDay(String(label))}</p>
      {payload.map((entry) => (
        <div key={String(entry.name)} className="flex items-center gap-2 text-[12px]">
          <span className="size-2 rounded-full" style={{ background: entry.color }} />
          <span className="text-muted-foreground">{entry.name}</span>
          <span className="tabular ml-auto pl-4 font-medium">
            {entry.value === null || entry.value === undefined ? "–" : `${entry.value}${unit}`}
          </span>
        </div>
      ))}
    </div>
  );
}

export function formatDay(day: string) {
  const date = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(date.getTime())
    ? day
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
