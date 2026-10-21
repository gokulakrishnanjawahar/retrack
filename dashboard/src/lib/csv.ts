export type Column = { key: string; label: string };

// Text that a spreadsheet would run as a formula (CSV injection). Numbers are left alone, so
// negative values stay numeric.
const FORMULA_START = /^[=+\-@\t\r]/;

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = typeof value === "number" ? String(value) : String(value);
  if (typeof value !== "number" && FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

// RFC 4180 CSV with CRLF line endings.
export function toCsv(columns: Column[], rows: Record<string, unknown>[]): string {
  const lines = [columns.map((c) => cell(c.label)).join(",")];
  for (const row of rows) lines.push(columns.map((c) => cell(row[c.key])).join(","));
  return lines.join("\r\n") + "\r\n";
}
