"use client";

import { motion } from "motion/react";
import { Fragment, useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { cn } from "@/lib/utils";

export type Snippet = { label: string; language: "python" | "shell"; code: string };

const PY_KEYWORDS = new Set(["from", "import", "def", "return", "for", "in", "with", "as", "if", "None", "True", "False"]);
const TOKEN_RE = /(#.*$|"[^"]*"|'[^']*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b|\s+|.)/gm;

// A tiny highlighter for the few snippets the dashboard shows (no extra dependency).
function highlight(code: string, language: Snippet["language"]) {
  return code.split("\n").map((line, i) => (
    <Fragment key={i}>
      {line.match(TOKEN_RE)?.map((token, j) => {
        let cls = "";
        if (token.startsWith("#")) cls = "text-faint";
        else if (token.startsWith('"') || token.startsWith("'")) cls = "text-[oklch(0.82_0.11_160)]";
        else if (/^\d/.test(token)) cls = "text-[oklch(0.82_0.12_75)]";
        else if (language === "python" && PY_KEYWORDS.has(token)) cls = "text-[oklch(0.76_0.15_300)]";
        else if (language === "shell" && j === 0) cls = "text-[oklch(0.76_0.15_300)]";
        return (
          <span key={j} className={cls}>
            {token}
          </span>
        );
      })}
      {"\n"}
    </Fragment>
  ));
}

export function CodeBlock({ snippets, className }: { snippets: Snippet[]; className?: string }) {
  const [active, setActive] = useState(0);
  const snippet = snippets[active];
  return (
    <div className={cn("overflow-hidden rounded-xl border border-border bg-[oklch(0.115_0.004_270)]", className)}>
      <div className="flex items-center justify-between border-b border-border px-2">
        <div className="flex">
          {snippets.map((s, i) => (
            <button
              key={s.label}
              type="button"
              onClick={() => setActive(i)}
              className={cn(
                "relative px-3 py-2.5 text-[12px] font-medium transition-colors",
                i === active ? "text-foreground" : "text-faint hover:text-muted-foreground",
              )}
            >
              {s.label}
              {i === active ? (
                <motion.span layoutId={`code-tab-${snippets[0].label}`} className="absolute inset-x-2 -bottom-px h-px bg-brand" />
              ) : null}
            </button>
          ))}
        </div>
        <CopyButton value={snippet.code} />
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-[12.5px] leading-relaxed text-foreground/90">
        <code>{highlight(snippet.code, snippet.language)}</code>
      </pre>
    </div>
  );
}

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
