import { describe, expect, it } from "vitest";
import type { DailyPoint } from "./data";
import { change, lift, MIN_HOLDOUT_EVIDENCE, rollingRates } from "./metrics";

const group = (successes: number, known: number, avg_tokens: number | null = null) => ({
  runs: known,
  known,
  successes,
  avg_tokens,
  avg_cost: null,
});

describe("lift", () => {
  it("is treated minus holdout success rate in points, with token change", () => {
    const result = lift(group(80, 100, 900), group(12, 20, 1000));
    expect(result.points).toBeCloseTo(20);
    expect(result.tokenChange).toBeCloseTo(-0.1);
    expect(result.enoughEvidence).toBe(true);
  });

  it("is not measured until the holdout has enough known outcomes", () => {
    const result = lift(group(9, 10), group(1, MIN_HOLDOUT_EVIDENCE - 1));
    expect(result.enoughEvidence).toBe(false);
    expect(lift(group(9, 10), null).points).toBeNull();
  });
});

describe("rollingRates", () => {
  const day = (i: number, ts: number, tk: number, hs: number, hk: number): DailyPoint => ({
    day: `2026-10-${String(i).padStart(2, "0")}`,
    runs: tk + hk,
    successes: ts + hs,
    failures: tk - ts + hk - hs,
    treated_known: tk,
    treated_successes: ts,
    holdout_known: hk,
    holdout_successes: hs,
  });

  it("pools the trailing window and leaves empty windows null", () => {
    const rates = rollingRates([day(1, 0, 0, 0, 0), day(2, 3, 4, 1, 2), day(3, 1, 1, 0, 0)], 2);
    expect(rates[0]).toEqual({ day: "2026-10-01", memory: null, holdout: null });
    expect(rates[1]).toEqual({ day: "2026-10-02", memory: 75, holdout: 50 });
    expect(rates[2]).toEqual({ day: "2026-10-03", memory: 80, holdout: 50 });
  });
});

describe("change", () => {
  it("is relative and undefined without a baseline", () => {
    expect(change(150, 100)).toBeCloseTo(0.5);
    expect(change(5, 0)).toBeNull();
  });
});
