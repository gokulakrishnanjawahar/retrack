import { PROJECT_COLUMNS } from "@/lib/admin-export";
import { toCsv } from "@/lib/csv";
import { getAdminProjectStats } from "@/lib/data";

// Super-admin analytics as CSV, one row per project. Anyone else gets a 404 (getAdminProjectStats).
export async function GET(request: Request) {
  const raw = Number(new URL(request.url).searchParams.get("days") ?? 30);
  const days = Number.isFinite(raw) ? Math.min(90, Math.max(7, Math.round(raw))) : 30;
  const rows = await getAdminProjectStats(days);
  const date = new Date().toISOString().slice(0, 10);
  return new Response(toCsv(PROJECT_COLUMNS, rows), {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="retrack-projects-${days}d-${date}.csv"`,
      "Cache-Control": "private, no-store",
    },
  });
}
