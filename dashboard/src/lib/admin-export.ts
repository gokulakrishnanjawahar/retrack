import type { Column } from "@/lib/csv";

// Columns of the super-admin CSV export (one row per project).
export const PROJECT_COLUMNS: Column[] = [
  { key: "organization", label: "Organization" },
  { key: "project", label: "Project" },
  { key: "project_id", label: "Project ID" },
  { key: "created_at", label: "Created" },
  { key: "members", label: "Members" },
  { key: "runs", label: "Runs" },
  { key: "known", label: "Runs with known outcome" },
  { key: "successes", label: "Successes" },
  { key: "success_rate", label: "Success rate" },
  { key: "lift_points", label: "Memory lift (points)" },
  { key: "holdout_known", label: "Holdout runs with known outcome" },
  { key: "recalls", label: "Recalls" },
  { key: "recall_hit_rate", label: "Recall hit rate" },
  { key: "agent_tokens", label: "Agent tokens" },
  { key: "agent_cost_usd", label: "Agent cost (USD)" },
  { key: "llm_input_tokens", label: "Retrack LLM input tokens" },
  { key: "llm_output_tokens", label: "Retrack LLM output tokens" },
  { key: "playbooks_active", label: "Active playbooks" },
  { key: "failure_signatures", label: "Failure signatures" },
  { key: "open_reviews", label: "Open reviews" },
  { key: "last_run_at", label: "Last run" },
];
