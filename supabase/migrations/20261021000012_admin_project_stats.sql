-- Super-admin analytics per project (docs/features.md block L: usage, runs, recalls, success
-- rates, costs), for the /admin table and its CSV export. The overview also reports the
-- platform's 30-day success rate and the agents' own cost.

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
    'success_rate_30d', (
      select (count(*) filter (where outcome = 'success'))::float
             / nullif(count(*) filter (where outcome <> 'unknown'), 0)
        from public.runs where created_at > now() - interval '30 days'),
    'agent_cost_30d', (
      select coalesce(sum(cost_usd), 0)::float from public.runs
       where created_at > now() - interval '30 days'),
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

-- One row per project for the super admin's table and CSV export: usage, success rates (all
-- runs, and memory vs holdout), recall hit rate, costs and memory health over the last
-- p_days days (7-90).
create function public.dashboard_admin_project_stats(p_days integer default 30) returns jsonb
language plpgsql stable security definer
set search_path = ''
as $$
declare
  v_days integer := least(greatest(coalesce(p_days, 30), 7), 90);
  v_since timestamptz := now() - make_interval(days => least(greatest(coalesce(p_days, 30), 7), 90));
begin
  if not access.is_super_admin() then
    raise exception 'not allowed' using errcode = 'insufficient_privilege';
  end if;
  return coalesce((
    with r as (
      select r.project_id, r.outcome, r.holdout, r.tokens_in + r.tokens_out as tokens, r.cost_usd,
             exists (select 1 from public.recalls c
                      where c.project_id = r.project_id and c.run_id = r.id) as recalled
        from public.runs r where r.created_at > v_since
    ),
    run_stats as (
      select project_id, count(*) as runs,
             count(*) filter (where outcome <> 'unknown') as known,
             count(*) filter (where outcome = 'success') as successes,
             count(*) filter (where recalled and not holdout and outcome <> 'unknown') as m_known,
             count(*) filter (where recalled and not holdout and outcome = 'success') as m_successes,
             count(*) filter (where recalled and holdout and outcome <> 'unknown') as h_known,
             count(*) filter (where recalled and holdout and outcome = 'success') as h_successes,
             coalesce(sum(tokens), 0) as tokens, coalesce(sum(cost_usd), 0) as cost
        from r group by project_id
    ),
    recall_stats as (
      select project_id, count(*) as recalls, count(*) filter (where not holdout) as served,
             count(*) filter (where not holdout and cardinality(playbook_ids) > 0) as hits
        from public.recalls where created_at > v_since group by project_id
    ),
    usage as (
      select project_id, sum(llm_input_tokens) as llm_in, sum(llm_output_tokens) as llm_out
        from public.usage_daily where day > current_date - v_days group by project_id
    )
    select jsonb_agg(jsonb_build_object(
             'project_id', p.id,
             'project', p.name,
             'organization', o.name,
             'created_at', p.created_at,
             'members', (select count(*) from public.members m where m.org_id = p.org_id),
             'runs', coalesce(rs.runs, 0),
             'known', coalesce(rs.known, 0),
             'successes', coalesce(rs.successes, 0),
             'success_rate', rs.successes::float / nullif(rs.known, 0),
             'lift_points', case when rs.m_known > 0 and rs.h_known > 0
               then (rs.m_successes::float / rs.m_known - rs.h_successes::float / rs.h_known) * 100
             end,
             'holdout_known', coalesce(rs.h_known, 0),
             'recalls', coalesce(rc.recalls, 0),
             'recall_hit_rate', rc.hits::float / nullif(rc.served, 0),
             'agent_tokens', coalesce(rs.tokens, 0),
             'agent_cost_usd', coalesce(rs.cost, 0)::float,
             'llm_input_tokens', coalesce(u.llm_in, 0),
             'llm_output_tokens', coalesce(u.llm_out, 0),
             'playbooks_active', (select count(*) from public.playbooks pb
                                   where pb.project_id = p.id and pb.status = 'active'),
             'failure_signatures', (select count(*) from public.failure_signatures f
                                     where f.project_id = p.id),
             'open_reviews', (select count(*) from public.review_queue q
                               where q.project_id = p.id and q.status = 'open'),
             'last_run_at', (select max(created_at) from public.runs x where x.project_id = p.id))
           order by coalesce(rs.runs, 0) desc, p.created_at)
      from public.projects p
      join public.organizations o on o.id = p.org_id
      left join run_stats rs on rs.project_id = p.id
      left join recall_stats rc on rc.project_id = p.id
      left join usage u on u.project_id = p.id
  ), '[]');
end
$$;

revoke all on function public.dashboard_admin_project_stats(integer) from public, anon;
grant execute on function public.dashboard_admin_project_stats(integer) to authenticated;
