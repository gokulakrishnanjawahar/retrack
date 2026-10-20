export type DiffLine = { kind: "same" | "added" | "removed"; text: string };

// Line diff by longest common subsequence; playbook versions are short, so O(n·m) is fine.
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before ? before.split("\n") : [];
  const b = after ? after.split("\n") : [];
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ kind: "removed", text: a[i++] });
    } else {
      out.push({ kind: "added", text: b[j++] });
    }
  }
  while (i < a.length) out.push({ kind: "removed", text: a[i++] });
  while (j < b.length) out.push({ kind: "added", text: b[j++] });
  return out;
}

export function stepText(step: unknown): string {
  if (typeof step === "string") return step;
  if (step && typeof step === "object") {
    const s = step as Record<string, unknown>;
    const main = s.action ?? s.description ?? s.detail ?? s.text;
    const tool = s.tool ?? s.tool_name;
    if (typeof main === "string") return tool ? `${main} (${tool})` : main;
    return JSON.stringify(step);
  }
  return String(step);
}

const FIELDS: [string, string][] = [
  ["title", "Title"],
  ["task_pattern", "Task"],
  ["preconditions", "Preconditions"],
  ["steps", "Step"],
  ["pitfalls", "Pitfalls"],
];

// A playbook snapshot as lines, so two versions can be diffed meaningfully.
export function snapshotText(snapshot: Record<string, unknown>): string {
  const lines: string[] = [];
  for (const [key, label] of FIELDS) {
    const value = snapshot[key];
    if (key === "steps" && Array.isArray(value)) {
      value.forEach((step, i) => lines.push(`Step ${i + 1}: ${stepText(step)}`));
    } else if (typeof value === "string" && value.trim()) {
      lines.push(`${label}: ${value.trim()}`);
    }
  }
  return lines.join("\n");
}
