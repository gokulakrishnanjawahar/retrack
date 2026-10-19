-- Least privilege for the public API role: it may insert runs and steps and update a
-- run's outcome (feedback), but never trust or processing state. Firewall results are
-- written only through a function the worker role can call.

revoke update on public.runs, public.steps, public.agents from retrack_api;
grant update (outcome, outcome_source, confidence) on public.runs to retrack_api;

create function private.record_firewall_result(
  p_project_id uuid, p_run_id uuid, p_taint_level text, p_step_trust jsonb
) returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.steps as s
     set input_trust = p_step_trust ->> s.idx::text
   where s.project_id = p_project_id
     and s.run_id = p_run_id
     and p_step_trust ? s.idx::text;
  update public.runs
     set taint_level = p_taint_level, processed_at = now()
   where project_id = p_project_id and id = p_run_id;
  if not found then
    raise exception 'run % not found in project %', p_run_id, p_project_id;
  end if;
end
$$;

revoke all on function private.record_firewall_result(uuid, uuid, text, jsonb)
  from public, anon, authenticated;
grant execute on function private.record_firewall_result(uuid, uuid, text, jsonb)
  to retrack_worker;
