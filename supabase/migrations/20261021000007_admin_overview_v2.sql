-- Phase 12e: the super-admin overview also reports dashboard users, a 30-day runs series
-- across all projects, and the latest run of each Supabase Cron job (worker health).

create or replace function public.dashboard_admin_overview() returns jsonb
language plpgsql stable security definer
set search_path = ''
as $$
begin
  if not access.is_super_admin() then
    raise exception 'not allowed' using errcode = 'insufficient_privilege';
  end if;
  return jsonb_build_object(
    'organizations', (select count(*) from public.organizations),
    'projects', (select count(*) from public.projects),
    'users', (select count(*) from auth.users),
    'users_7d', (select count(*) from auth.users where created_at > now() - interval '7 days'),
    'runs_total', (select count(*) from public.runs),
    'runs_7d', (select count(*) from public.runs where created_at > now() - interval '7 days'),
    'playbooks_active', (select count(*) from public.playbooks where status = 'active'),
    'reviews_open', (select count(*) from public.review_queue where status = 'open'),
    'queue_depth', (select count(*) from pgmq.q_runs),
    'dead_letters', (select count(*) from pgmq.q_runs_dlq),
    'usage_30d', (
      select jsonb_build_object(
        'runs', coalesce(sum(runs_captured), 0), 'recalls', coalesce(sum(recalls_served), 0),
        'llm_input_tokens', coalesce(sum(llm_input_tokens), 0),
        'llm_output_tokens', coalesce(sum(llm_output_tokens), 0))
        from public.usage_daily where day > current_date - 30),
    'top_projects', coalesce((
      select jsonb_agg(t) from (
        select p.id, p.name as project, o.name as organization, count(r.id) as runs_7d
          from public.projects p join public.organizations o on o.id = p.org_id
          left join public.runs r on r.project_id = p.id
            and r.created_at > now() - interval '7 days'
         group by p.id, p.name, o.name order by runs_7d desc limit 10) t), '[]'),
    'daily', (
      select jsonb_agg(jsonb_build_object('day', d.day, 'runs', d.runs) order by d.day)
        from (
          select g.day::date as day, count(r.id) as runs
            from generate_series(current_date - 29, current_date, interval '1 day') as g(day)
            left join public.runs r on r.created_at >= g.day and r.created_at < g.day + interval '1 day'
           group by g.day
        ) d),
    'cron', coalesce((
      select jsonb_agg(jsonb_build_object(
               'job', j.jobname, 'schedule', j.schedule, 'active', j.active,
               'status', d.status, 'last_run', d.end_time) order by j.jobname)
        from cron.job j
        left join lateral (
          select status, end_time from cron.job_run_details
           where jobid = j.jobid order by start_time desc limit 1) d on true), '[]')
  );
end
$$;
