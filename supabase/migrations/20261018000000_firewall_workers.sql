-- Phase 3: firewall core (trust settings, processed runs) and background workers.
--
--   * projects.trusted_tools / task_trusted: the server's source of truth for taint.
--     Default: nothing trusted (docs/firewall.md, "Untrusted by default").
--   * retrack_worker: the only role that can read or remove queue jobs. Workers then
--     touch customer data through retrack_api inside a project scope, like requests.
--   * runs_dlq: jobs that keep failing are moved here for inspection.
--   * Supabase Cron calls POST /internal/drain every minute while jobs are waiting.
--     The URL and secret live in Supabase Vault and are set outside migrations.

alter table public.projects
  add column trusted_tools text[] not null default '{}',
  add column task_trusted boolean not null default false;

alter table public.runs add column processed_at timestamptz;

select pgmq.create('runs_dlq');

create role retrack_worker nologin noinherit;
grant retrack_worker to retrack_server;
grant retrack_worker to postgres;
grant usage on schema private to retrack_worker;

create function private.read_run_jobs(p_batch integer, p_visibility_seconds integer)
returns table (msg_id bigint, read_ct integer, project_id uuid, run_id uuid)
language sql
security definer
set search_path = ''
as $$
  select m.msg_id, m.read_ct, (m.message->>'project_id')::uuid, (m.message->>'run_id')::uuid
  from pgmq.read('runs', p_visibility_seconds, p_batch) as m
$$;

create function private.complete_run_job(p_msg_id bigint) returns boolean
language sql
security definer
set search_path = ''
as $$ select pgmq.delete('runs', p_msg_id) $$;

create function private.dead_letter_run_job(p_msg_id bigint, p_error text) returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_message jsonb;
begin
  select q.message into v_message from pgmq.q_runs as q where q.msg_id = p_msg_id;
  if v_message is null then
    return;
  end if;
  perform pgmq.send(
    'runs_dlq',
    v_message || jsonb_build_object('error', left(p_error, 1000), 'failed_at', now())
  );
  perform pgmq.delete('runs', p_msg_id);
end
$$;

revoke all on function private.read_run_jobs(integer, integer) from public, anon, authenticated;
revoke all on function private.complete_run_job(bigint) from public, anon, authenticated;
revoke all on function private.dead_letter_run_job(bigint, text) from public, anon, authenticated;
grant execute on function private.read_run_jobs(integer, integer) to retrack_worker;
grant execute on function private.complete_run_job(bigint) to retrack_worker;
grant execute on function private.dead_letter_run_job(bigint, text) to retrack_worker;

-- Supabase Cron ------------------------------------------------------------------------

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron with schema pg_catalog;

-- Calls the drain endpoint only when it is configured and a job is ready, so idle
-- minutes cost no function invocation.
select cron.schedule(
  'retrack-drain-runs',
  '* * * * *',
  $$
  select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'retrack_drain_url'),
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Retrack-Worker-Secret',
      (select decrypted_secret from vault.decrypted_secrets where name = 'retrack_worker_secret')
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 60000
  )
  where exists (select 1 from vault.decrypted_secrets where name = 'retrack_drain_url')
    and exists (select 1 from pgmq.q_runs where vt <= now())
  $$
);
