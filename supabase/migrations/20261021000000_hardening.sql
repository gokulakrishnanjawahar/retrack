-- Hardening: one-call ingest, per-project rate limiting, data retention.
--
--   * private.ingest_run: verifies the API key, applies the rate limit and stores the run
--     with its steps, outcome hint, queue message and usage in ONE call. It runs as the
--     caller (retrack_api), so row-level security still applies to every write.
--   * private.resolve_outcome: the single definition of "which signal wins", used by
--     ingest and by POST /v1/feedback.
--   * projects.ingest_rate_limit (runs per minute, default 600) + ingest_counters.
--   * private.enforce_retention: daily (Supabase Cron) deletion of runs older than the
--     project's retention_days, except runs that support live memory (provenance),
--     which are kept until that memory is retired.

alter table public.projects
  add column ingest_rate_limit integer not null default 600 check (ingest_rate_limit > 0);

create table public.ingest_counters (
  project_id uuid not null references public.projects (id) on delete cascade,
  window_start timestamptz not null,
  requests integer not null default 0,
  primary key (project_id, window_start)
);

alter table public.ingest_counters enable row level security;
revoke all on public.ingest_counters from anon, authenticated;
grant select, insert, update on public.ingest_counters to retrack_api;
create policy project_isolation on public.ingest_counters for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());

-- Outcome resolution -------------------------------------------------------------------

create function private.resolve_outcome(p_project_id uuid, p_run_id uuid) returns void
language sql
set search_path = ''
as $$
  update public.runs as r
     set outcome = s.outcome, outcome_source = s.source, confidence = s.confidence
    from (
      select source, outcome, confidence from public.outcome_signals
       where project_id = p_project_id and run_id = p_run_id
       order by case source when 'test' then 3 when 'event' then 2 when 'feedback' then 1
                else 0 end desc, seq desc
       limit 1
    ) as s
   where r.project_id = p_project_id and r.id = p_run_id
$$;

revoke all on function private.resolve_outcome(uuid, uuid) from public, anon, authenticated;
grant execute on function private.resolve_outcome(uuid, uuid) to retrack_api, retrack_pipeline;

-- One-call ingest ----------------------------------------------------------------------

create function private.ingest_run(p_prefix text, p_key_hash text, p_run jsonb)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v_project_id uuid;
  v_limit integer;
  v_requests integer;
  v_agent_id uuid;
  v_run_id uuid := (p_run ->> 'id')::uuid;
  v_recalled uuid[];
  v_holdout boolean;
  v_hint jsonb := p_run -> 'outcome_hint';
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

  insert into public.agents (project_id, name) values (v_project_id, p_run ->> 'agent')
  on conflict (project_id, name) do nothing
  returning id into v_agent_id;
  if v_agent_id is null then
    select id into v_agent_id from public.agents
     where project_id = v_project_id and name = p_run ->> 'agent';
  end if;

  select coalesce(array_agg(distinct pb) filter (where pb is not null), '{}'),
         coalesce(bool_or(r.holdout), false)
    into v_recalled, v_holdout
    from public.recalls r left join lateral unnest(r.playbook_ids) pb on true
   where r.project_id = v_project_id and r.run_id = v_run_id;

  insert into public.runs (project_id, id, agent_id, task_text, model_id, tool_versions,
    tokens_in, tokens_out, cost_usd, latency_ms, output_text, recalled_playbook_ids, holdout)
  values (
    v_project_id, v_run_id, v_agent_id, p_run ->> 'task', p_run ->> 'model_id',
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
  select v_project_id, v_run_id, s.idx, s.type, s.tool_name, s.args_hash,
         coalesce(s.args_redacted, '{}'), s.result_class, s.error_class, s.latency_ms,
         s.tokens_in, s.tokens_out, coalesce(s.input_trust, 'untrusted'), s.result_redacted
    from jsonb_to_recordset(coalesce(p_run -> 'steps', '[]')) as s(
      idx integer, type text, tool_name text, args_hash text, args_redacted jsonb,
      result_class text, error_class text, latency_ms integer, tokens_in integer,
      tokens_out integer, input_trust text, result_redacted text);

  if v_hint is not null and jsonb_typeof(v_hint) = 'object' then
    insert into public.outcome_signals (project_id, run_id, source, outcome, confidence)
    values (
      v_project_id, v_run_id, v_hint ->> 'source', v_hint ->> 'outcome',
      case v_hint ->> 'source' when 'test' then 1.0 when 'event' then 0.9 else 0.8 end
    );
    perform private.resolve_outcome(v_project_id, v_run_id);
  end if;

  perform private.enqueue_run(v_run_id);
  perform private.increment_usage(
    1, 0, 0,
    coalesce((p_run ->> 'tokens_in')::bigint, 0) + coalesce((p_run ->> 'tokens_out')::bigint, 0)
  );
  return jsonb_build_object('status', 'stored');
end
$$;

revoke all on function private.ingest_run(text, text, jsonb) from public, anon, authenticated;
grant execute on function private.ingest_run(text, text, jsonb) to retrack_api;

-- Retention ----------------------------------------------------------------------------

create function private.enforce_retention() returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_runs integer;
  v_recalls integer;
  v_results integer;
begin
  create temporary table expired_runs on commit drop as
  select r.project_id, r.id
    from public.runs r join public.projects p on p.id = r.project_id
   where r.created_at < now() - make_interval(days => p.retention_days)
     and not exists (
       select 1 from public.provenance pv
         join public.playbooks pb on pb.id = pv.object_id and pb.project_id = pv.project_id
        where pv.project_id = r.project_id and pv.object_type = 'playbook'
          and pb.status <> 'retired' and r.id = any(pv.source_run_ids));

  delete from public.firewall_findings f using expired_runs e
   where f.project_id = e.project_id and f.object_type = 'run' and f.object_id = e.id;
  delete from public.runs r using expired_runs e
   where r.project_id = e.project_id and r.id = e.id;
  get diagnostics v_runs = row_count;

  delete from public.recalls r using public.projects p
   where p.id = r.project_id and r.created_at < now() - make_interval(days => p.retention_days);
  get diagnostics v_recalls = row_count;
  delete from public.eval_results r using public.projects p
   where p.id = r.project_id and r.created_at < now() - make_interval(days => p.retention_days);
  get diagnostics v_results = row_count;
  delete from public.embedding_cache c using public.projects p
   where p.id = c.project_id and c.created_at < now() - make_interval(days => p.retention_days);
  delete from public.ingest_counters where window_start < now() - interval '1 day';
  delete from pgmq.q_runs_dlq where enqueued_at < now() - interval '30 days';

  return jsonb_build_object('runs', v_runs, 'recalls', v_recalls, 'eval_results', v_results);
end
$$;

revoke all on function private.enforce_retention() from public, anon, authenticated;

select cron.schedule('retrack-retention', '17 3 * * *', 'select private.enforce_retention()');
