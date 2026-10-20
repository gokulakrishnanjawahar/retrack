import type { Snippet } from "@/components/code-block";

// The SDK quickstart shown in onboarding and on an empty overview.
export function quickstartSnippets(apiUrl: string, secret?: string): Snippet[] {
  const key = secret ?? "rtk_live_…";
  return [
    { label: "Install", language: "shell", code: `pip install retrack\n\nexport RETRACK_API_KEY="${key}"\nexport RETRACK_BASE_URL="${apiUrl}"` },
    {
      label: "Capture",
      language: "python",
      code: `from retrack import Retrack\n\nrt = Retrack("support-agent")  # reads RETRACK_API_KEY and RETRACK_BASE_URL\n\n# Every LangGraph run is captured, verified and learned from.\nresult = graph.invoke(inputs, config={"callbacks": [rt.callback()]})`,
    },
    {
      label: "Recall",
      language: "python",
      code: `memory = rt.recall(task)  # fails open: never blocks your agent\n\nresult = graph.invoke(\n    {"messages": [("system", memory.as_prompt()), ("user", task)]},\n    config={"callbacks": [rt.callback()]},\n)`,
    },
  ];
}
