-- Fix: dashboard_project_overview nested an aggregate inside jsonb_agg for the daily series
-- (GroupingError). The per-day counts are now computed in a subquery first.

create or replace function public.dashboard_project_overview(
  p_project_id uuid, p_days integer default 30
) returns jsonb
language plpgsql stable
set search_path = ''
as $$
declare
  v_days integer := least(greatest(coalesce(p_days, 30), 7), 90);
  v_since date := current_date - (v_days - 1);
begin
  if not exists (select 1 from public.projects where id = p_project_id) then
    return null;
  end if;
  return (
    with r as (
      select r.created_at, r.created_at::date as day, r.outcome, r.holdout, r.taint_level,
             r.tokens_in + r.tokens_out as tokens, r.cost_usd,
             exists (select 1 from public.recalls c
                      where c.project_id = r.project_id and c.run_id = r.id) as recalled
        from public.runs r
       where r.project_id = p_project_id
         and r.created_at >= least(v_since, current_date - 13)
    ),
    groups as (
      select holdout,
             count(*) as runs,
             count(*) filter (where outcome <> 'unknown') as known,
             count(*) filter (where outcome = 'success') as successes,
             avg(tokens) as avg_tokens,
             avg(cost_usd) as avg_cost
        from r where recalled and day >= v_since
       group by holdout
    ),
    daily as (
      select d.day::date as day,
             count(r.day) as runs,
             count(*) filter (where r.outcome = 'success') as successes,
             count(*) filter (where r.outcome = 'failure') as failures,
             count(*) filter (where r.recalled and not r.holdout
                                and r.outcome <> 'unknown') as treated_known,
             count(*) filter (where r.recalled and not r.holdout
                                and r.outcome = 'success') as treated_successes,
             count(*) filter (where r.recalled and r.holdout
                                and r.outcome <> 'unknown') as holdout_known,
             count(*) filter (where r.recalled and r.holdout
                                and r.outcome = 'success') as holdout_successes
        from generate_series(v_since, current_date, interval '1 day') as d(day)
        left join r on r.day = d.day::date
       group by d.day
    )
    select jsonb_build_object(
      'kpis', (
        select jsonb_build_object(
          'runs_7d', count(*) filter (where created_at > now() - interval '7 days'),
          'runs_prev_7d', count(*) filter (where created_at <= now() - interval '7 days'
                                             and created_at > now() - interval '14 days'),
          'success_rate_7d',
            (count(*) filter (where outcome = 'success'
                                and created_at > now() - interval '7 days'))::real
            / nullif(count(*) filter (where outcome <> 'unknown'
                                        and created_at > now() - interval '7 days'), 0),
          'success_rate_prev_7d',
            (count(*) filter (where outcome = 'success'
                                and created_at <= now() - interval '7 days'
                                and created_at > now() - interval '14 days'))::real
            / nullif(count(*) filter (where outcome <> 'unknown'
                                        and created_at <= now() - interval '7 days'
                                        and created_at > now() - interval '14 days'), 0),
          'tokens_7d',
            coalesce(sum(tokens) filter (where created_at > now() - interval '7 days'), 0),
          'quarantined_7d', count(*) filter (where taint_level = 'quarantined'
                                               and created_at > now() - interval '7 days'),
          'recalls_7d', (select count(*) from public.recalls
                          where project_id = p_project_id
                            and created_at > now() - interval '7 days'),
          'playbooks', (select coalesce(jsonb_object_agg(status, n), '{}') from (
                          select status, count(*) as n from public.playbooks
                           where project_id = p_project_id group by status) s),
          'failure_signatures', (select count(*) from public.failure_signatures
                                  where project_id = p_project_id),
          'open_reviews', (select count(*) from public.review_queue
                            where project_id = p_project_id and status = 'open'))
          from r),
      'roi', jsonb_build_object(
        'treated', (select to_jsonb(g) - 'holdout' from groups g where not holdout),
        'holdout', (select to_jsonb(g) - 'holdout' from groups g where holdout)),
      'daily', (select jsonb_agg(to_jsonb(x) order by x.day) from daily x)
    )
  );
end
$$;
