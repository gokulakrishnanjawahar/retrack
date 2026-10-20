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
