import "server-only";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { createClient } from "@/lib/supabase/server";

// Data access for pages. Every read runs as the signed-in user, so row-level security
// limits it to projects of organizations they belong to.

export type Role = "owner" | "admin" | "member";

export type ProjectSummary = { id: string; name: string; orgId: string; organization: string };

export type Project = ProjectSummary & {
  trustedTools: string[];
  taskTrusted: boolean;
  holdoutRate: number;
  retentionDays: number;
  ingestRateLimit: number;
  createdAt: string;
};

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const getUser = cache(async () => {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (!claims?.sub) redirect("/login");
  return { id: claims.sub, email: typeof claims.email === "string" ? claims.email : "" };
});

type ProjectRow = {
  id: string;
  name: string;
  org_id: string;
  organizations: { name: string } | null;
};

export const listProjects = cache(async (): Promise<ProjectSummary[]> => {
  await getUser();
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("projects")
    .select("id, name, org_id, organizations(name)")
    .order("created_at")
    .returns<ProjectRow[]>();
  if (error) throw new Error(error.message);
  return data.map((p) => ({
    id: p.id,
    name: p.name,
    orgId: p.org_id,
    organization: p.organizations?.name ?? "",
  }));
});

export const getProject = cache(async (projectId: string): Promise<Project> => {
  if (!UUID_RE.test(projectId)) notFound();
  await getUser();
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("projects")
    .select(
      "id, name, org_id, trusted_tools, task_trusted, holdout_rate, retention_days," +
        " ingest_rate_limit, created_at, organizations(name)",
    )
    .eq("id", projectId)
    .maybeSingle<
      ProjectRow & {
        trusted_tools: string[];
        task_trusted: boolean;
        holdout_rate: number;
        retention_days: number;
        ingest_rate_limit: number;
        created_at: string;
      }
    >();
  if (error) throw new Error(error.message);
  if (!data) notFound();
  return {
    id: data.id,
    name: data.name,
    orgId: data.org_id,
    organization: data.organizations?.name ?? "",
    trustedTools: data.trusted_tools,
    taskTrusted: data.task_trusted,
    holdoutRate: data.holdout_rate,
    retentionDays: data.retention_days,
    ingestRateLimit: data.ingest_rate_limit,
    createdAt: data.created_at,
  };
});

export const getRole = cache(async (projectId: string): Promise<Role | null> => {
  const [project, user] = await Promise.all([getProject(projectId), getUser()]);
  const supabase = await createClient();
  const { data } = await supabase
    .from("members")
    .select("role")
    .eq("org_id", project.orgId)
    .eq("user_id", user.id)
    .maybeSingle<{ role: Role }>();
  return data?.role ?? null;
});

export const isSuperAdmin = cache(async (): Promise<boolean> => {
  await getUser();
  const supabase = await createClient();
  const { data } = await supabase.rpc("dashboard_is_super_admin");
  return data === true;
});

export async function listKeys(projectId: string): Promise<ApiKey[]> {
  await getProject(projectId);
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("api_keys")
    .select("id, name, prefix, created_at, last_used_at, revoked_at")
    .eq("project_id", projectId)
    .order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  return data.map((k) => ({
    id: k.id,
    name: k.name,
    prefix: k.prefix,
    createdAt: k.created_at,
    lastUsedAt: k.last_used_at,
    revokedAt: k.revoked_at,
  }));
}

// Overview ------------------------------------------------------------------------------

export type RoiGroup = {
  runs: number;
  known: number;
  successes: number;
  avg_tokens: number | null;
  avg_cost: number | null;
};

export type DailyPoint = {
  day: string;
  runs: number;
  successes: number;
  failures: number;
  treated_known: number;
  treated_successes: number;
  holdout_known: number;
  holdout_successes: number;
};

export type Overview = {
  kpis: {
    runs_7d: number;
    runs_prev_7d: number;
    success_rate_7d: number | null;
    success_rate_prev_7d: number | null;
    tokens_7d: number;
    quarantined_7d: number;
    recalls_7d: number;
    playbooks: Partial<Record<"candidate" | "active" | "quarantined" | "retired", number>>;
    failure_signatures: number;
    open_reviews: number;
  };
  roi: { treated: RoiGroup | null; holdout: RoiGroup | null };
  daily: DailyPoint[];
};

export async function getOverview(projectId: string, days = 30): Promise<Overview> {
  await getProject(projectId);
  const supabase = await createClient();
  const { data, error } = await supabase.rpc("dashboard_project_overview", {
    p_project_id: projectId,
    p_days: days,
  });
  if (error) throw new Error(error.message);
  if (!data) notFound();
  return data as Overview;
}

export type RunRow = {
  id: string;
  agent_id: string;
  task_text: string;
  model_id: string;
  outcome: "success" | "failure" | "unknown";
  outcome_source: string | null;
  taint_level: "trusted" | "untrusted" | "quarantined";
  holdout: boolean;
  recalled_playbook_ids: string[];
  tokens_in: number;
  tokens_out: number;
  latency_ms: number | null;
  created_at: string;
};

export const RUN_COLUMNS =
  "id, agent_id, task_text, model_id, outcome, outcome_source, taint_level, holdout," +
  " recalled_playbook_ids, tokens_in, tokens_out, latency_ms, created_at";

export async function listRecentRuns(projectId: string, limit = 12): Promise<RunRow[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("runs")
    .select(RUN_COLUMNS)
    .eq("project_id", projectId)
    .order("created_at", { ascending: false })
    .limit(limit)
    .returns<RunRow[]>();
  if (error) throw new Error(error.message);
  return data;
}

export async function listAgents(projectId: string): Promise<Record<string, string>> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("agents")
    .select("id, name")
    .eq("project_id", projectId)
    .returns<{ id: string; name: string }[]>();
  if (error) throw new Error(error.message);
  return Object.fromEntries(data.map((a) => [a.id, a.name]));
}

export type TopPlaybook = { id: string; title: string; uses: number; success_rate: number };

export async function listTopPlaybooks(projectId: string, limit = 5): Promise<TopPlaybook[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("playbooks")
    .select("id, title, uses, success_rate")
    .eq("project_id", projectId)
    .eq("status", "active")
    .order("uses", { ascending: false })
    .limit(limit)
    .returns<TopPlaybook[]>();
  if (error) throw new Error(error.message);
  return data;
}

// Memory ---------------------------------------------------------------------------------

export type PlaybookStatus = "candidate" | "active" | "quarantined" | "retired";

export type PlaybookSummary = {
  id: string;
  agent_id: string;
  title: string;
  status: PlaybookStatus;
  uses: number;
  successes: number;
  success_rate: number;
  confidence: number;
  trusted_support: number;
  untrusted_sources: number;
  quarantined_sources: number;
  support_count: number;
  validated_models: string[];
  last_success_at: string | null;
  version: number;
  updated_at: string;
};

export async function listPlaybooks(projectId: string): Promise<PlaybookSummary[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("playbooks")
    .select(
      "id, agent_id, title, status, uses, successes, success_rate, confidence, trusted_support," +
        " untrusted_sources, quarantined_sources, support_count, validated_models," +
        " last_success_at, version, updated_at",
    )
    .eq("project_id", projectId)
    .order("updated_at", { ascending: false })
    .limit(500)
    .returns<PlaybookSummary[]>();
  if (error) throw new Error(error.message);
  return data;
}

export type Step = { action?: string; tool?: string; detail?: string; [key: string]: unknown };

export type PlaybookDetail = PlaybookSummary & {
  task_pattern: string;
  preconditions: string;
  steps: Step[] | string[];
  pitfalls: string;
  tool_versions: Record<string, string>;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  versions: { version: number; snapshot: Record<string, unknown>; change_reason: string; created_at: string }[];
  provenance: { source_run_ids: string[]; input_sources: string[]; trust_level: string; reviewer_id: string | null } | null;
  findings: Finding[];
  evalCase: { status: string; last_result: string | null; last_model_id: string | null; last_run_at: string | null } | null;
};

export type Finding = { id: string; object_id: string; check_name: string; severity: "flag" | "block"; detail: string; created_at: string };

export async function getPlaybook(projectId: string, playbookId: string): Promise<PlaybookDetail> {
  if (!UUID_RE.test(playbookId)) notFound();
  const supabase = await createClient();
  const [playbook, versions, provenance, findings, evalCase] = await Promise.all([
    supabase
      .from("playbooks")
      .select(
        "id, agent_id, title, status, uses, successes, success_rate, confidence, trusted_support," +
          " untrusted_sources, quarantined_sources, support_count, validated_models, last_success_at," +
          " version, updated_at, task_pattern, preconditions, steps, pitfalls, tool_versions," +
          " approved_by, approved_at, created_at",
      )
      .eq("project_id", projectId)
      .eq("id", playbookId)
      .maybeSingle(),
    supabase
      .from("playbook_versions")
      .select("version, snapshot, change_reason, created_at")
      .eq("playbook_id", playbookId)
      .order("version", { ascending: false }),
    supabase
      .from("provenance")
      .select("source_run_ids, input_sources, trust_level, reviewer_id")
      .eq("object_type", "playbook")
      .eq("object_id", playbookId)
      .maybeSingle(),
    supabase
      .from("firewall_findings")
      .select("id, object_id, check_name, severity, detail, created_at")
      .eq("object_type", "playbook")
      .eq("object_id", playbookId)
      .order("created_at", { ascending: false }),
    supabase
      .from("eval_cases")
      .select("status, last_result, last_model_id, last_run_at")
      .eq("source", "playbook")
      .eq("source_id", playbookId)
      .maybeSingle(),
  ]);
  if (playbook.error) throw new Error(playbook.error.message);
  if (!playbook.data) notFound();
  return {
    ...(playbook.data as unknown as PlaybookSummary & Omit<PlaybookDetail, "versions" | "provenance" | "findings" | "evalCase">),
    versions: (versions.data ?? []) as PlaybookDetail["versions"],
    provenance: (provenance.data ?? null) as PlaybookDetail["provenance"],
    findings: (findings.data ?? []) as Finding[],
    evalCase: (evalCase.data ?? null) as PlaybookDetail["evalCase"],
  };
}

export type FailureSignature = {
  id: string;
  agent_id: string;
  tool_name: string;
  error_class: string;
  input_shape: string;
  occurrences: number;
  recoveries: number;
  unrecoverable: boolean;
  unrecoverable_override: boolean | null;
  recovery_steps: unknown[];
  first_seen: string;
  last_seen: string;
};

export async function listFailureSignatures(projectId: string): Promise<FailureSignature[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("failure_signatures")
    .select(
      "id, agent_id, tool_name, error_class, input_shape, occurrences, recoveries, unrecoverable," +
        " unrecoverable_override, recovery_steps, first_seen, last_seen",
    )
    .eq("project_id", projectId)
    .order("occurrences", { ascending: false })
    .limit(300)
    .returns<FailureSignature[]>();
  if (error) throw new Error(error.message);
  return data;
}

// Review ---------------------------------------------------------------------------------

export type ReviewItem = {
  id: string;
  object_type: "playbook" | "failure_signature";
  object_id: string;
  reason: string;
  created_at: string;
  playbook: Pick<PlaybookDetail, "id" | "title" | "status" | "task_pattern" | "steps" | "pitfalls" | "trusted_support" | "untrusted_sources" | "quarantined_sources"> | null;
  findings: Finding[];
};

export async function listOpenReviews(projectId: string): Promise<ReviewItem[]> {
  const supabase = await createClient();
  const { data: items, error } = await supabase
    .from("review_queue")
    .select("id, object_type, object_id, reason, created_at")
    .eq("project_id", projectId)
    .eq("status", "open")
    .order("created_at")
    .returns<Omit<ReviewItem, "playbook" | "findings">[]>();
  if (error) throw new Error(error.message);
  const ids = items.map((i) => i.object_id);
  if (ids.length === 0) return [];
  const [playbooks, findings] = await Promise.all([
    supabase
      .from("playbooks")
      .select("id, title, status, task_pattern, steps, pitfalls, trusted_support, untrusted_sources, quarantined_sources")
      .in("id", ids),
    supabase
      .from("firewall_findings")
      .select("id, object_id, check_name, severity, detail, created_at")
      .in("object_id", ids),
  ]);
  const byId = new Map((playbooks.data ?? []).map((p) => [p.id as string, p]));
  return items.map((item) => ({
    ...item,
    playbook: (byId.get(item.object_id) ?? null) as ReviewItem["playbook"],
    findings: ((findings.data ?? []) as Finding[]).filter((f) => f.object_id === item.object_id),
  }));
}

export async function countOpenReviews(projectId: string): Promise<number> {
  const supabase = await createClient();
  const { count } = await supabase
    .from("review_queue")
    .select("id", { count: "exact", head: true })
    .eq("project_id", projectId)
    .eq("status", "open");
  return count ?? 0;
}

export async function listQuarantinedRuns(projectId: string): Promise<(RunRow & { findings: Finding[] })[]> {
  const supabase = await createClient();
  const { data: runs, error } = await supabase
    .from("runs")
    .select(RUN_COLUMNS)
    .eq("project_id", projectId)
    .eq("taint_level", "quarantined")
    .order("created_at", { ascending: false })
    .limit(50)
    .returns<RunRow[]>();
  if (error) throw new Error(error.message);
  if (runs.length === 0) return [];
  const { data: findings } = await supabase
    .from("firewall_findings")
    .select("id, object_id, check_name, severity, detail, created_at")
    .eq("object_type", "run")
    .in("object_id", runs.map((r) => r.id));
  return runs.map((run) => ({ ...run, findings: ((findings ?? []) as Finding[]).filter((f) => f.object_id === run.id) }));
}

// Runs -----------------------------------------------------------------------------------

export type RunFilters = { outcome?: string; q?: string; agent?: string; before?: string };

export const RUNS_PAGE = 40;

export async function listRuns(projectId: string, filters: RunFilters): Promise<RunRow[]> {
  const supabase = await createClient();
  let query = supabase.from("runs").select(RUN_COLUMNS).eq("project_id", projectId);
  if (filters.outcome === "quarantined") query = query.eq("taint_level", "quarantined");
  else if (filters.outcome && ["success", "failure", "unknown"].includes(filters.outcome)) {
    query = query.eq("outcome", filters.outcome);
  }
  if (filters.agent && UUID_RE.test(filters.agent)) query = query.eq("agent_id", filters.agent);
  if (filters.q) query = query.ilike("task_text", `%${filters.q.replace(/[%_\\]/g, (c) => `\\${c}`)}%`);
  if (filters.before && !Number.isNaN(Date.parse(filters.before))) query = query.lt("created_at", filters.before);
  const { data, error } = await query
    .order("created_at", { ascending: false })
    .limit(RUNS_PAGE)
    .returns<RunRow[]>();
  if (error) throw new Error(error.message);
  return data;
}

export type StepRow = {
  idx: number;
  type: "llm" | "tool";
  tool_name: string | null;
  args_redacted: Record<string, unknown> | null;
  result_class: string | null;
  error_class: string | null;
  result_redacted: string | null;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  input_trust: "trusted" | "untrusted";
};

export type RunDetail = RunRow & {
  output_text: string | null;
  cost_usd: number | null;
  confidence: number | null;
  replay_of: string | null;
  steps: StepRow[];
  signals: { source: string; outcome: string; confidence: number; created_at: string }[];
  findings: Finding[];
  recall: { mode: string; latency_ms: number | null; playbook_ids: string[]; warning_ids: string[] } | null;
  playbookTitles: Record<string, string>;
};

export async function getRun(projectId: string, runId: string): Promise<RunDetail> {
  if (!UUID_RE.test(runId)) notFound();
  const supabase = await createClient();
  const [run, steps, signals, findings, recall] = await Promise.all([
    supabase
      .from("runs")
      .select(`${RUN_COLUMNS}, output_text, cost_usd, confidence, replay_of`)
      .eq("project_id", projectId)
      .eq("id", runId)
      .maybeSingle(),
    supabase
      .from("steps")
      .select("idx, type, tool_name, args_redacted, result_class, error_class, result_redacted, latency_ms, tokens_in, tokens_out, input_trust")
      .eq("project_id", projectId)
      .eq("run_id", runId)
      .order("idx"),
    supabase
      .from("outcome_signals")
      .select("source, outcome, confidence, created_at")
      .eq("project_id", projectId)
      .eq("run_id", runId)
      .order("created_at"),
    supabase
      .from("firewall_findings")
      .select("id, object_id, check_name, severity, detail, created_at")
      .eq("object_type", "run")
      .eq("object_id", runId),
    supabase
      .from("recalls")
      .select("mode, latency_ms, playbook_ids, warning_ids")
      .eq("project_id", projectId)
      .eq("run_id", runId)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);
  if (run.error) throw new Error(run.error.message);
  if (!run.data) notFound();
  const ids = [...new Set([...((run.data as unknown as RunRow).recalled_playbook_ids ?? []), ...((recall.data?.playbook_ids as string[]) ?? [])])];
  const titles = ids.length
    ? ((await supabase.from("playbooks").select("id, title").in("id", ids)).data ?? [])
    : [];
  return {
    ...(run.data as unknown as RunDetail),
    steps: (steps.data ?? []) as StepRow[],
    signals: (signals.data ?? []) as RunDetail["signals"],
    findings: (findings.data ?? []) as Finding[],
    recall: (recall.data ?? null) as RunDetail["recall"],
    playbookTitles: Object.fromEntries(titles.map((t) => [t.id as string, t.title as string])),
  };
}

// Recalls --------------------------------------------------------------------------------

export type RecallRow = {
  id: string;
  agent_id: string;
  run_id: string | null;
  playbook_ids: string[];
  warning_ids: string[];
  holdout: boolean;
  mode: "hybrid" | "keyword" | "holdout" | "no_agent";
  latency_ms: number | null;
  created_at: string;
};

export async function listRecalls(projectId: string): Promise<{
  recalls: RecallRow[];
  titles: Record<string, string>;
  outcomes: Record<string, RunRow["outcome"]>;
  tasks: Record<string, string>;
}> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("recalls")
    .select("id, agent_id, run_id, playbook_ids, warning_ids, holdout, mode, latency_ms, created_at")
    .eq("project_id", projectId)
    .order("created_at", { ascending: false })
    .limit(100)
    .returns<RecallRow[]>();
  if (error) throw new Error(error.message);
  const playbookIds = [...new Set(data.flatMap((r) => r.playbook_ids))];
  const runIds = data.map((r) => r.run_id).filter((id): id is string => Boolean(id));
  const [titles, runs] = await Promise.all([
    playbookIds.length ? supabase.from("playbooks").select("id, title").in("id", playbookIds) : Promise.resolve({ data: [] }),
    runIds.length
      ? supabase.from("runs").select("id, outcome, task_text").eq("project_id", projectId).in("id", runIds)
      : Promise.resolve({ data: [] }),
  ]);
  const runRows = (runs.data ?? []) as { id: string; outcome: RunRow["outcome"]; task_text: string }[];
  return {
    recalls: data,
    titles: Object.fromEntries(((titles.data ?? []) as { id: string; title: string }[]).map((t) => [t.id, t.title])),
    outcomes: Object.fromEntries(runRows.map((r) => [r.id, r.outcome])),
    tasks: Object.fromEntries(runRows.map((r) => [r.id, r.task_text])),
  };
}

// Regression and migration -----------------------------------------------------------------

export type Assertion = { type: string; tools?: string[]; tool?: string; error_class?: string; text?: string };

export type EvalCase = {
  id: string;
  agent_id: string;
  source: "playbook" | "failure";
  source_id: string;
  input: { task?: string };
  expected_assertions: Assertion[];
  critical: boolean;
  status: "active" | "retired";
  last_result: "passed" | "failed" | null;
  last_model_id: string | null;
  last_run_at: string | null;
};

export async function listEvalCases(projectId: string): Promise<EvalCase[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("eval_cases")
    .select("id, agent_id, source, source_id, input, expected_assertions, critical, status, last_result, last_model_id, last_run_at")
    .eq("project_id", projectId)
    .eq("status", "active")
    .order("critical", { ascending: false })
    .order("last_run_at", { ascending: false, nullsFirst: false })
    .limit(500)
    .returns<EvalCase[]>();
  if (error) throw new Error(error.message);
  return data;
}

export type TestRun = { id: string; model: string | null; migrationId: string | null; passed: number; total: number; at: string };

export async function listTestRuns(projectId: string): Promise<TestRun[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("eval_results")
    .select("test_run_id, passed, model_id, migration_id, created_at")
    .eq("project_id", projectId)
    .order("created_at", { ascending: false })
    .limit(3000)
    .returns<{ test_run_id: string; passed: boolean; model_id: string | null; migration_id: string | null; created_at: string }[]>();
  if (error) throw new Error(error.message);
  const runs = new Map<string, TestRun>();
  for (const row of data) {
    const run = runs.get(row.test_run_id) ?? { id: row.test_run_id, model: row.model_id, migrationId: row.migration_id, passed: 0, total: 0, at: row.created_at };
    run.total += 1;
    run.passed += row.passed ? 1 : 0;
    if (row.created_at < run.at) run.at = row.created_at;
    runs.set(row.test_run_id, run);
  }
  return [...runs.values()].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 30);
}

export type MigrationCounts = Partial<Record<"passes" | "needs_relearning" | "breaks" | "fixed" | "returns", number>>;

export type MigrationReport = {
  id: string;
  agent_id: string;
  from_model: string | null;
  to_model: string;
  model_applied: boolean;
  status: "running" | "completed";
  summary: {
    counts?: MigrationCounts;
    items?: { case_id: string; source: "playbook" | "failure"; source_id: string; title: string; result: keyof MigrationCounts; failures: string[] }[];
  } | null;
  created_at: string;
  completed_at: string | null;
};

const MIGRATION_COLUMNS = "id, agent_id, from_model, to_model, model_applied, status, summary, created_at, completed_at";

export async function listMigrations(projectId: string): Promise<MigrationReport[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("migration_reports")
    .select(MIGRATION_COLUMNS)
    .eq("project_id", projectId)
    .order("created_at", { ascending: false })
    .limit(50)
    .returns<MigrationReport[]>();
  if (error) throw new Error(error.message);
  return data;
}

export async function getMigration(projectId: string, migrationId: string): Promise<MigrationReport> {
  if (!UUID_RE.test(migrationId)) notFound();
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("migration_reports")
    .select(MIGRATION_COLUMNS)
    .eq("project_id", projectId)
    .eq("id", migrationId)
    .maybeSingle<MigrationReport>();
  if (error) throw new Error(error.message);
  if (!data) notFound();
  return data;
}

// Super admin ----------------------------------------------------------------------------

export type AdminOverview = {
  organizations: number;
  projects: number;
  users: number;
  users_7d: number;
  runs_total: number;
  runs_7d: number;
  playbooks_active: number;
  reviews_open: number;
  queue_depth: number;
  dead_letters: number;
  usage_30d: { runs: number; recalls: number; llm_input_tokens: number; llm_output_tokens: number };
  top_projects: { id: string; project: string; organization: string; runs_7d: number }[];
  daily: { day: string; runs: number }[];
  cron: { job: string; schedule: string; active: boolean; status: string | null; last_run: string | null }[];
};

// Cross-project analytics. Anyone who is not a super admin gets a 404, not a hint.
export async function getAdminOverview(): Promise<AdminOverview> {
  await getUser();
  if (!(await isSuperAdmin())) notFound();
  const supabase = await createClient();
  const { data, error } = await supabase.rpc("dashboard_admin_overview");
  if (error) {
    if (error.code === "42501") notFound();
    throw new Error(error.message);
  }
  return data as AdminOverview;
}
