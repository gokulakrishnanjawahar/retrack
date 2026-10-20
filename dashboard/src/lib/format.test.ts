import { describe, expect, it } from "vitest";
import { timeAgo } from "./format";

const NOW = Date.parse("2026-10-20T12:00:00Z");

describe("timeAgo", () => {
  it.each([
    ["2026-10-20T11:59:30Z", "just now"],
    ["2026-10-20T11:55:00Z", "5 minutes ago"],
    ["2026-10-20T09:00:00Z", "3 hours ago"],
    ["2026-10-19T12:00:00Z", "yesterday"],
    ["2026-10-06T12:00:00Z", "2 weeks ago"],
  ])("%s → %s", (iso, expected) => {
    expect(timeAgo(iso, NOW)).toBe(expected);
  });
});
