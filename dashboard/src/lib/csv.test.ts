import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";

describe("toCsv", () => {
  it("writes a header and quotes cells that need it", () => {
    const csv = toCsv(
      [
        { key: "name", label: "Project" },
        { key: "runs", label: "Runs" },
      ],
      [
        { name: 'Acme, "prod"', runs: 12 },
        { name: "line\nbreak", runs: 0 },
      ],
    );
    expect(csv).toBe('Project,Runs\r\n"Acme, ""prod""",12\r\n"line\nbreak",0\r\n');
  });

  it("neutralises spreadsheet formulas in text but keeps negative numbers", () => {
    const csv = toCsv(
      [
        { key: "name", label: "Project" },
        { key: "lift", label: "Lift" },
      ],
      [
        { name: "=HYPERLINK(\"http://x\")", lift: -4.5 },
        { name: "@cmd", lift: null },
        { name: "+1", lift: 3 },
      ],
    );
    expect(csv.split("\r\n")).toEqual([
      "Project,Lift",
      "\"'=HYPERLINK(\"\"http://x\"\")\",-4.5",
      "'@cmd,",
      "'+1,3",
      "",
    ]);
  });
});
