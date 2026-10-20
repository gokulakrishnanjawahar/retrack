import type { DailyPoint, RoiGroup } from "@/lib/data";

// Holdout runs with a known outcome needed before the lift is shown as measured.
export const MIN_HOLDOUT_EVIDENCE = 20;

export function rate(successes: number, known: number): number | null {
  return known > 0 ? successes / known : null;
}

export type Lift = {
  treatedRate: number | null;
  holdoutRate: number | null;
  points: number | null; // percentage points, treated minus holdout
  tokenChange: number | null; // relative change in tokens per run, treated vs holdout
  enoughEvidence: boolean;
};

export function lift(treated: RoiGroup | null, holdout: RoiGroup | null): Lift {
  const treatedRate = treated ? rate(treated.successes, treated.known) : null;
  const holdoutRate = holdout ? rate(holdout.successes, holdout.known) : null;
  const points =
    treatedRate !== null && holdoutRate !== null ? (treatedRate - holdoutRate) * 100 : null;
  const tokenChange =
    treated?.avg_tokens && holdout?.avg_tokens
      ? treated.avg_tokens / holdout.avg_tokens - 1
      : null;
  return {
    treatedRate,
    holdoutRate,
    points,
    tokenChange,
    enoughEvidence: (holdout?.known ?? 0) >= MIN_HOLDOUT_EVIDENCE && (treated?.known ?? 0) > 0,
  };
}

// Success rate over a trailing window, per day, for the memory and holdout groups.
export function rollingRates(daily: DailyPoint[], window = 7) {
  return daily.map((point, i) => {
    const slice = daily.slice(Math.max(0, i - window + 1), i + 1);
    const sum = (key: keyof DailyPoint) => slice.reduce((acc, p) => acc + (p[key] as number), 0);
    const treated = rate(sum("treated_successes"), sum("treated_known"));
    const holdout = rate(sum("holdout_successes"), sum("holdout_known"));
    return {
      day: point.day,
      memory: treated === null ? null : Math.round(treated * 1000) / 10,
      holdout: holdout === null ? null : Math.round(holdout * 1000) / 10,
    };
  });
}

export function change(current: number, previous: number): number | null {
  return previous > 0 ? current / previous - 1 : null;
}
