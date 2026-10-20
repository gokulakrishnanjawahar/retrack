-- Phase 11 recovery and plan replay (docs/regression-migration.md, docs/recall-gating.md).
--
--   * failure_signatures.recovery_steps / recoveries: what a successful run did between
--     hitting this failure and succeeding with the same tool (a known fix).
--   * unrecoverable is set automatically (5+ occurrences, never recovered) unless an
--     admin set unrecoverable_override.
--   * runs.replay_of: the playbook whose plan the run replayed; a failed replay demotes it.

alter table public.failure_signatures
  add column recovery_steps jsonb not null default '[]',
  add column recoveries integer not null default 0,
  add column unrecoverable_override boolean;

alter table public.runs add column replay_of uuid;

create or replace function private.store_run_payload(p_project_id uuid, p_run jsonb) returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v_agent_id uuid;
  v_run_id uuid := (p_run ->> 'id')::uuid;
  v_recalled uuid[];
  v_holdout boolean;
  v_hint jsonb := p_run -> 'outcome_hint';
begin
  perform set_config('app.project_id', p_project_id::text, true);
  insert into public.agents (project_id, name) values (p_project_id, p_run ->> 'agent')
  on conflict (project_id, name) do nothing
  returning id into v_agent_id;
  if v_agent_id is null then
    select id into v_agent_id from public.agents
     where project_id = p_project_id and name = p_run ->> 'agent';
  end if;

  select coalesce(array_agg(distinct pb) filter (where pb is not null), '{}'),
         coalesce(bool_or(r.holdout), false)
    into v_recalled, v_holdout
    from public.recalls r left join lateral unnest(r.playbook_ids) pb on true
   where r.project_id = p_project_id and r.run_id = v_run_id;

  insert into public.runs (project_id, id, agent_id, task_text, model_id, tool_versions,
    tokens_in, tokens_out, cost_usd, latency_ms, output_text, recalled_playbook_ids, holdout,
    replay_of)
  values (
    p_project_id, v_run_id, v_agent_id, p_run ->> 'task', p_run ->> 'model_id',
    coalesce(p_run -> 'tool_versions', '{}'), coalesce((p_run ->> 'tokens_in')::integer, 0),
    coalesce((p_run ->> 'tokens_out')::integer, 0), (p_run ->> 'cost_usd')::numeric,
    (p_run ->> 'latency_ms')::integer, p_run ->> 'output', v_recalled, v_holdout,
    (p_run ->> 'replay_of')::uuid
  )
  on conflict (project_id, id) do nothing;
  if not found then
    return jsonb_build_object('status', 'duplicate');
  end if;

  insert into public.steps (project_id, run_id, idx, type, tool_name, args_hash, args_redacted,
    result_class, error_class, latency_ms, tokens_in, tokens_out, input_trust, result_redacted)
  select p_project_id, v_run_id, s.idx, s.type, s.tool_name, s.args_hash,
         coalesce(s.args_redacted, '{}'), s.result_class, s.error_class, s.latency_ms,
         s.tokens_in, s.tokens_out, coalesce(s.input_trust, 'untrusted'), s.result_redacted
    from jsonb_to_recordset(coalesce(p_run -> 'steps', '[]')) as s(
      idx integer, type text, tool_name text, args_hash text, args_redacted jsonb,
      result_class text, error_class text, latency_ms integer, tokens_in integer,
      tokens_out integer, input_trust text, result_redacted text);

  if v_hint is not null and jsonb_typeof(v_hint) = 'object' then
    insert into public.outcome_signals (project_id, run_id, source, outcome, confidence)
    values (
      p_project_id, v_run_id, v_hint ->> 'source', v_hint ->> 'outcome',
      case v_hint ->> 'source' when 'test' then 1.0 when 'event' then 0.9 else 0.8 end
    );
    perform private.resolve_outcome(p_project_id, v_run_id);
  end if;

  perform private.enqueue_run(v_run_id);
  perform private.increment_usage(
    1, 0, 0,
    coalesce((p_run ->> 'tokens_in')::bigint, 0) + coalesce((p_run ->> 'tokens_out')::bigint, 0)
  );
  return jsonb_build_object('status', 'stored');
end
$$;

