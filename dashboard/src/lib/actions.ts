"use server";

import { revalidatePath } from "next/cache";
import { getUser } from "@/lib/data";
import { generateKey, hashKey } from "@/lib/keys";
import { createClient } from "@/lib/supabase/server";

// Every action re-checks the session here, and the database function it calls checks the
// caller's role again (owner or admin), so a forged request cannot act on another project.

export type ActionResult<T = object> = ({ ok: true } & T) | { ok: false; error: string };

function message(error: { code?: string; message: string }) {
  switch (error.code) {
    case "42501":
      return "You need owner or admin access to this project.";
    case "23514":
      return "One of the values is out of range.";
    case "22023":
      return error.message;
    default:
      return "Something went wrong. Try again.";
  }
}

async function addKey(projectId: string, name: string, env: "live" | "test") {
  const pepper = process.env.RETRACK_KEY_PEPPER;
  if (!pepper) throw new Error("RETRACK_KEY_PEPPER is not set");
  const key = generateKey(env);
  const supabase = await createClient();
  const { error } = await supabase.rpc("dashboard_add_api_key", {
    p_project_id: projectId,
    p_name: name,
    p_prefix: key.prefix,
    p_key_hash: hashKey(key.secret, pepper),
  });
  return { key, error };
}

export async function createWorkspace(input: {
  organization: string;
  project: string;
}): Promise<ActionResult<{ projectId: string; secret: string }>> {
  await getUser();
  const organization = input.organization.trim();
  const project = input.project.trim();
  if (!organization || !project) return { ok: false, error: "Give both a name." };
  const supabase = await createClient();
  const { data: projectId, error } = await supabase.rpc("dashboard_create_workspace", {
    p_org_name: organization,
    p_project_name: project,
  });
  if (error) return { ok: false, error: message(error) };
  const { key, error: keyError } = await addKey(projectId as string, "default", "live");
  if (keyError) return { ok: false, error: message(keyError) };
  revalidatePath("/", "layout");
  return { ok: true, projectId: projectId as string, secret: key.secret };
}

export async function createApiKey(
  projectId: string,
  input: { name: string; env: "live" | "test" },
): Promise<ActionResult<{ secret: string }>> {
  await getUser();
  const name = input.name.trim() || "default";
  const env = input.env === "test" ? "test" : "live";
  const { key, error } = await addKey(projectId, name, env);
  if (error) return { ok: false, error: message(error) };
  revalidatePath(`/p/${projectId}/keys`);
  return { ok: true, secret: key.secret };
}

export async function revokeApiKey(projectId: string, keyId: string): Promise<ActionResult> {
  await getUser();
  const supabase = await createClient();
  const { error } = await supabase.rpc("dashboard_revoke_api_key", { p_key_id: keyId });
  if (error) return { ok: false, error: message(error) };
  revalidatePath(`/p/${projectId}/keys`);
  return { ok: true };
}

export async function updateProjectSettings(
  projectId: string,
  input: {
    trustedTools: string[];
    taskTrusted: boolean;
    holdoutRate: number;
    retentionDays: number;
    ingestRateLimit: number;
  },
): Promise<ActionResult> {
  await getUser();
  const tools = [...new Set(input.trustedTools.map((t) => t.trim()).filter(Boolean))].sort();
  const supabase = await createClient();
  const { error } = await supabase.rpc("dashboard_update_project", {
    p_project_id: projectId,
    p_trusted_tools: tools,
    p_task_trusted: input.taskTrusted,
    p_holdout_rate: input.holdoutRate,
    p_retention_days: Math.round(input.retentionDays),
    p_ingest_rate_limit: Math.round(input.ingestRateLimit),
  });
  if (error) return { ok: false, error: message(error) };
  revalidatePath(`/p/${projectId}`, "layout");
  return { ok: true };
}

export async function resolveReview(
  projectId: string,
  itemId: string,
  approve: boolean,
  note: string,
): Promise<ActionResult> {
  await getUser();
  const supabase = await createClient();
  const { error } = await supabase.rpc("dashboard_resolve_review", {
    p_item_id: itemId,
    p_approve: approve,
    p_note: note.slice(0, 1000),
  });
  if (error) return { ok: false, error: message(error) };
  revalidatePath(`/p/${projectId}`, "layout");
  return { ok: true };
}

export async function setPlaybookStatus(
  projectId: string,
  playbookId: string,
  status: "quarantined" | "retired",
  note: string,
): Promise<ActionResult> {
  await getUser();
  const supabase = await createClient();
  const { error } = await supabase.rpc("dashboard_set_playbook_status", {
    p_playbook_id: playbookId,
    p_status: status,
    p_note: note.slice(0, 500),
  });
  if (error) return { ok: false, error: message(error) };
  revalidatePath(`/p/${projectId}`, "layout");
  return { ok: true };
}
