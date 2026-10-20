import { describe, expect, it } from "vitest";
import { diffLines, snapshotText } from "./diff";

describe("diffLines", () => {
  it("marks kept, removed and added lines in order", () => {
    expect(diffLines("a\nb\nc", "a\nc\nd")).toEqual([
      { kind: "same", text: "a" },
      { kind: "removed", text: "b" },
      { kind: "same", text: "c" },
      { kind: "added", text: "d" },
    ]);
  });

  it("handles empty sides", () => {
    expect(diffLines("", "x")).toEqual([{ kind: "added", text: "x" }]);
    expect(diffLines("x", "")).toEqual([{ kind: "removed", text: "x" }]);
  });
});

describe("snapshotText", () => {
  it("renders the playbook fields in a stable, readable order", () => {
    const text = snapshotText({
      pitfalls: "Do not refund twice",
      title: "Refund",
      steps: [{ action: "Look up the order" }, "Issue the refund"],
    });
    expect(text.split("\n")).toEqual([
      "Title: Refund",
      "Step 1: Look up the order",
      "Step 2: Issue the refund",
      "Pitfalls: Do not refund twice",
    ]);
  });
});
