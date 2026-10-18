-- Phase 4 scoring: every outcome signal is kept; the run stores the winning one.
--
--   * outcome_signals: test results, business events and user feedback (from the SDK or
--     POST /v1/feedback), plus the AI judge's verdict when no hard signal exists.
--   * usage_daily.llm_*_tokens: Retrack's own LLM spend, per project per day.

create table public.outcome_signals (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null,
  run_id uuid not null,
  source text not null check (source in ('test', 'event', 'feedback', 'judge')),
  outcome text not null check (outcome in ('success', 'failure')),
  confidence real not null check (confidence between 0 and 1),
  detail jsonb not null default '{}',
  created_at timestamptz not null default now(),
  foreign key (project_id, run_id) references public.runs (project_id, id) on delete cascade
);

create index outcome_signals_run_idx on public.outcome_signals (project_id, run_id);

alter table public.outcome_signals enable row level security;
revoke all on public.outcome_signals from anon, authenticated;
grant select, insert on public.outcome_signals to retrack_api;

create policy project_isolation on public.outcome_signals for all to retrack_api
  using (project_id = private.current_project_id())
  with check (project_id = private.current_project_id());

alter table public.usage_daily
  add column llm_input_tokens bigint not null default 0,
  add column llm_output_tokens bigint not null default 0;

-- Adds to today's LLM token counters (UTC) for the project set in `app.project_id`.
create function private.increment_llm_usage(p_input_tokens bigint, p_output_tokens bigint)
returns void
language sql
set search_path = ''
as $$
  insert into public.usage_daily as u (project_id, day, llm_input_tokens, llm_output_tokens)
  values (
    private.current_project_id(), (now() at time zone 'utc')::date,
    p_input_tokens, p_output_tokens
  )
  on conflict (project_id, day) do update set
    llm_input_tokens = u.llm_input_tokens + excluded.llm_input_tokens,
    llm_output_tokens = u.llm_output_tokens + excluded.llm_output_tokens
$$;

revoke all on function private.increment_llm_usage(bigint, bigint) from public, anon, authenticated;
grant execute on function private.increment_llm_usage(bigint, bigint) to retrack_api;
