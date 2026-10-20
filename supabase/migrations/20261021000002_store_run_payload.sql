-- Split ingest: private.store_run_payload stores an already-authorised run (one
-- definition, used by private.ingest_run and by trusted server code); ingest_run keeps
-- the key check and rate limit.

create function private.store_run_payload(p_project_id uuid, p_run jsonb) returns jsonb
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
    tokens_in, tokens_out, cost_usd, latency_ms, output_text, recalled_playbook_ids, holdout)
  values (
    p_project_id, v_run_id, v_agent_id, p_run ->> 'task', p_run ->> 'model_id',
    coalesce(p_run -> 'tool_versions', '{}'), coalesce((p_run ->> 'tokens_in')::integer, 0),
    coalesce((p_run ->> 'tokens_out')::integer, 0), (p_run ->> 'cost_usd')::numeric,
    (p_run ->> 'latency_ms')::integer, p_run ->> 'output', v_recalled, v_holdout
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

revoke all on function private.store_run_payload(uuid, jsonb) from public, anon, authenticated;
grant execute on function private.store_run_payload(uuid, jsonb) to retrack_api;

create or replace function private.ingest_run(p_prefix text, p_key_hash text, p_run jsonb)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v_project_id uuid;
  v_limit integer;
  v_requests integer;
begin
  v_project_id := private.verify_api_key(p_prefix, p_key_hash);
  if v_project_id is null then
    return jsonb_build_object('status', 'unauthorized');
  end if;
  perform set_config('app.project_id', v_project_id::text, true);

  select ingest_rate_limit into v_limit from public.projects where id = v_project_id;
  insert into public.ingest_counters as c (project_id, window_start, requests)
  values (v_project_id, date_trunc('minute', now()), 1)
  on conflict (project_id, window_start) do update set requests = c.requests + 1
  returning requests into v_requests;
  if v_requests > v_limit then
    return jsonb_build_object(
      'status', 'rate_limited',
      'retry_after', greatest(1, 60 - extract(second from now())::integer)
    );
  end if;
  return private.store_run_payload(v_project_id, p_run);
end
$$;
