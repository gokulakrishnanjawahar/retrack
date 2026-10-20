import { Pill } from "@/components/badges";
import type { Assertion } from "@/lib/data";

export function AssertionChips({ assertions }: { assertions: Assertion[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {assertions.map((a, i) => {
        if (a.type === "tool_sequence") {
          return a.tools?.length ? <Pill key={i}>{a.tools.join(" → ")}</Pill> : null;
        }
        if (a.type === "no_failure") {
          return (
            <Pill key={i} tone="danger">
              not {a.tool} {a.error_class}
            </Pill>
          );
        }
        if (a.type === "completes") return <Pill key={i}>completes</Pill>;
        return <Pill key={i}>{a.type}</Pill>;
      })}
    </div>
  );
}
