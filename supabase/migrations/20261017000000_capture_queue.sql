-- Phase 2 capture: run-processing queue and the server's own database login.
--
--   * pgmq queue `runs`: one message per newly ingested run, {project_id, run_id}.
--     Workers (Phase 3+) read it via /internal/drain, triggered by Supabase Cron.
--   * `retrack_api` can only add to the queue through private.enqueue_run, which takes the
--     project from `app.project_id`, so a request can never enqueue another project's run.
--   * `retrack_server` is the login the deployed server uses. It has no privileges of its
--     own; it can only switch to `retrack_api`. Its password is set outside migrations
--     (see CLAUDE.md), so no secret is committed.

create extension if not exists pgmq;
select pgmq.create('runs');

create function private.enqueue_run(p_run_id uuid) returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_project_id uuid := private.current_project_id();
begin
  if v_project_id is null
     or not exists (select 1 from public.runs where project_id = v_project_id and id = p_run_id)
  then
    raise exception 'run % not found in current project', p_run_id;
  end if;
  return pgmq.send(
    'runs', jsonb_build_object('project_id', v_project_id, 'run_id', p_run_id)
  );
end
$$;

revoke all on function private.enqueue_run(uuid) from public, anon, authenticated;
grant execute on function private.enqueue_run(uuid) to retrack_api;

create role retrack_server login noinherit;
grant retrack_api to retrack_server;
