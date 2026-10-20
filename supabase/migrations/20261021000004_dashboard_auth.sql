-- Phase 12a: dashboard access with Supabase Auth.
--
--   * members.user_id -> auth.users; roles owner / admin / member.
--   * super_admins: accounts that may see cross-project analytics (Gokul only).
--   * Logged-in users (role `authenticated`) can READ only projects of organizations they
--     belong to, enforced by row-level security. They never write tables directly: every
--     change goes through a public.dashboard_* function that checks their role.
--   * api_keys: logged-in users can see a key's prefix and dates, never its hash.
--   * Realtime: runs are published so the dashboard can stream new runs live (RLS applies).
--   * The membership helpers live in schema `access` (not exposed by the API), so the
--     `authenticated` role never gets usage on `private`.

alter table public.members
  add constraint members_user_fk foreign key (user_id) references auth.users (id)
  on delete cascade,
  add constraint members_role_check check (role in ('owner', 'admin', 'member'));

create table public.super_admins (
  user_id uuid primary key references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);
alter table public.super_admins enable row level security;
revoke all on public.super_admins from anon, authenticated;

-- Helpers ------------------------------------------------------------------------------

create schema access;
revoke all on schema access from public;
grant usage on schema access to authenticated;

create function access.my_project_ids() returns setof uuid
language sql stable security definer
set search_path = ''
as $$
  select p.id from public.projects p
    join public.members m on m.org_id = p.org_id
   where m.user_id = auth.uid()
$$;

create function access.my_org_ids() returns setof uuid
language sql stable security definer
set search_path = ''
as $$ select org_id from public.members where user_id = auth.uid() $$;

create function access.project_role(p_project_id uuid) returns text
language sql stable security definer
set search_path = ''
as $$
  select m.role from public.projects p
    join public.members m on m.org_id = p.org_id
   where p.id = p_project_id and m.user_id = auth.uid()
$$;

create function access.is_super_admin() returns boolean
language sql stable security definer
set search_path = ''
as $$ select exists (select 1 from public.super_admins where user_id = auth.uid()) $$;

create function access.require_project_admin(p_project_id uuid) returns void
language plpgsql stable security definer
set search_path = ''
as $$
begin
  if coalesce(access.project_role(p_project_id), '') not in ('owner', 'admin') then
    raise exception 'not allowed' using errcode = 'insufficient_privilege';
  end if;
end
$$;

revoke all on function access.my_project_ids(), access.my_org_ids(),
  access.project_role(uuid), access.is_super_admin(), access.require_project_admin(uuid)
  from public, anon;
grant execute on function access.my_project_ids(), access.my_org_ids(),
  access.project_role(uuid), access.is_super_admin(), access.require_project_admin(uuid)
  to authenticated;

-- Read access ----------------------------------------------------------------------------

grant select on public.organizations, public.members, public.projects, public.agents,
  public.runs, public.steps, public.outcome_signals, public.playbooks,
  public.playbook_versions, public.failure_signatures, public.provenance,
  public.review_queue, public.firewall_findings, public.eval_cases, public.eval_results,
  public.migration_reports, public.recalls, public.usage_daily
  to authenticated;
grant select (id, project_id, prefix, name, created_at, last_used_at, revoked_at)
  on public.api_keys to authenticated;

create policy dashboard_members_read on public.organizations for select to authenticated
  using (id in (select access.my_org_ids()));
create policy dashboard_members_read on public.members for select to authenticated
  using (org_id in (select access.my_org_ids()));
create policy dashboard_members_read on public.projects for select to authenticated
  using (id in (select access.my_project_ids()));

do $$
declare
  t text;
begin
  foreach t in array array[
    'agents', 'runs', 'steps', 'outcome_signals', 'playbooks', 'playbook_versions',
    'failure_signatures', 'provenance', 'review_queue', 'firewall_findings', 'eval_cases',
    'eval_results', 'migration_reports', 'recalls', 'usage_daily', 'api_keys'
  ] loop
    execute format(
      'create policy dashboard_members_read on public.%I for select to authenticated'
      ' using (project_id in (select access.my_project_ids()))',
      t
    );
  end loop;
end
$$;

alter publication supabase_realtime add table public.runs;

-- Actions (all check the caller's role) ------------------------------------------------

create function public.dashboard_create_workspace(p_org_name text, p_project_name text)
returns uuid
language plpgsql security definer
set search_path = ''
as $$
declare
  v_org_id uuid;
  v_project_id uuid;
begin
  if auth.uid() is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;
  if coalesce(trim(p_org_name), '') = '' or coalesce(trim(p_project_name), '') = '' then
    raise exception 'names must not be empty' using errcode = 'invalid_parameter_value';
  end if;
  insert into public.organizations (name) values (left(trim(p_org_name), 100))
  returning id into v_org_id;
  insert into public.members (org_id, user_id, role) values (v_org_id, auth.uid(), 'owner');
  insert into public.projects (org_id, name) values (v_org_id, left(trim(p_project_name), 100))
  returning id into v_project_id;
  return v_project_id;
end
$$;

create function public.dashboard_add_api_key(
  p_project_id uuid, p_name text, p_prefix text, p_key_hash text
) returns uuid
language plpgsql security definer
set search_path = ''
as $$
declare
  v_id uuid;
begin
  perform access.require_project_admin(p_project_id);
  if p_prefix !~ '^rtk_(live|test)_[0-9a-f]{8}$' or p_key_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid key' using errcode = 'invalid_parameter_value';
  end if;
  insert into public.api_keys (project_id, prefix, key_hash, name)
  values (p_project_id, p_prefix, p_key_hash, left(p_name, 100))
  returning id into v_id;
  return v_id;
end
$$;

create function public.dashboard_revoke_api_key(p_key_id uuid) returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  v_project_id uuid;
begin
  select project_id into v_project_id from public.api_keys where id = p_key_id;
  perform access.require_project_admin(v_project_id);
  update public.api_keys set revoked_at = now() where id = p_key_id and revoked_at is null;
end
$$;

create function public.dashboard_resolve_review(p_item_id uuid, p_approve boolean, p_note text)
returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  v_item record;
  v_reviewer text := coalesce(auth.jwt() ->> 'email', auth.uid()::text);
begin
  select project_id, object_type, object_id, status into v_item
    from public.review_queue where id = p_item_id;
  if not found then
    raise exception 'not found' using errcode = 'no_data_found';
  end if;
  perform access.require_project_admin(v_item.project_id);
  if v_item.status <> 'open' then
    raise exception 'already resolved' using errcode = 'invalid_parameter_value';
  end if;
  update public.review_queue
     set status = case when p_approve then 'approved' else 'rejected' end,
         reviewer = v_reviewer, resolution_note = left(p_note, 1000), resolved_at = now()
   where id = p_item_id;
  if v_item.object_type = 'playbook' then
    if p_approve then
      update public.playbooks set approved_by = v_reviewer, approved_at = now(), status = 'active'
       where id = v_item.object_id;
      update public.provenance set reviewer_id = v_reviewer, approved_at = now()
       where project_id = v_item.project_id and object_type = 'playbook'
         and object_id = v_item.object_id;
    else
      update public.playbooks set status = 'retired' where id = v_item.object_id;
    end if;
  end if;
end
$$;

create function public.dashboard_update_project(
  p_project_id uuid,
  p_trusted_tools text[],
  p_task_trusted boolean,
  p_holdout_rate real,
  p_retention_days integer,
  p_ingest_rate_limit integer
) returns void
language plpgsql security definer
set search_path = ''
as $$
begin
  perform access.require_project_admin(p_project_id);
  update public.projects
     set trusted_tools = coalesce(p_trusted_tools, trusted_tools),
         task_trusted = coalesce(p_task_trusted, task_trusted),
         holdout_rate = coalesce(p_holdout_rate, holdout_rate),
         retention_days = coalesce(p_retention_days, retention_days),
         ingest_rate_limit = coalesce(p_ingest_rate_limit, ingest_rate_limit)
   where id = p_project_id;
end
$$;

create function public.dashboard_is_super_admin() returns boolean
language sql stable security definer
set search_path = ''
as $$ select access.is_super_admin() $$;

create function public.dashboard_admin_overview() returns jsonb
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
        select p.name as project, o.name as organization, count(r.id) as runs_7d
          from public.projects p join public.organizations o on o.id = p.org_id
          left join public.runs r on r.project_id = p.id
            and r.created_at > now() - interval '7 days'
         group by p.id, p.name, o.name order by runs_7d desc limit 10) t), '[]')
  );
end
$$;

-- Overview for one project. Runs as the caller, so row-level security decides access:
-- a project the user cannot see returns null. ROI compares runs that asked for memory
-- (recall made, not holdout) with holdout runs, on known outcomes only.
create function public.dashboard_project_overview(p_project_id uuid, p_days integer default 30)
returns jsonb
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
    )
    select jsonb_build_object(
      'kpis', (
        select jsonb_build_object(
          'runs_7d', count(*) filter (where created_at > now() - interval '7 days'),
          'runs_prev_7d', count(*) filter (where created_at <= now() - interval '7 days'
                                             and created_at > now() - interval '14 days'),
          'success_rate_7d',
            (count(*) filter (where outcome = 'success' and created_at > now() - interval '7 days'))::real
            / nullif(count(*) filter (where outcome <> 'unknown'
                                        and created_at > now() - interval '7 days'), 0),
          'success_rate_prev_7d',
            (count(*) filter (where outcome = 'success' and created_at <= now() - interval '7 days'
                                and created_at > now() - interval '14 days'))::real
            / nullif(count(*) filter (where outcome <> 'unknown'
                                        and created_at <= now() - interval '7 days'
                                        and created_at > now() - interval '14 days'), 0),
          'tokens_7d', coalesce(sum(tokens) filter (where created_at > now() - interval '7 days'), 0),
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
      'daily', (
        select jsonb_agg(jsonb_build_object(
                 'day', d.day::date,
                 'runs', count(r.day),
                 'successes', count(*) filter (where r.outcome = 'success'),
                 'failures', count(*) filter (where r.outcome = 'failure'),
                 'treated_known', count(*) filter (where r.recalled and not r.holdout
                                                     and r.outcome <> 'unknown'),
                 'treated_successes', count(*) filter (where r.recalled and not r.holdout
                                                         and r.outcome = 'success'),
                 'holdout_known', count(*) filter (where r.recalled and r.holdout
                                                     and r.outcome <> 'unknown'),
                 'holdout_successes', count(*) filter (where r.recalled and r.holdout
                                                         and r.outcome = 'success'))
               order by d.day)
          from generate_series(v_since, current_date, interval '1 day') as d(day)
          left join r on r.day = d.day::date
         group by d.day)
    )
  );
end
$$;

revoke all on function public.dashboard_create_workspace(text, text),
  public.dashboard_add_api_key(uuid, text, text, text),
  public.dashboard_revoke_api_key(uuid),
  public.dashboard_resolve_review(uuid, boolean, text),
  public.dashboard_update_project(uuid, text[], boolean, real, integer, integer),
  public.dashboard_is_super_admin(),
  public.dashboard_admin_overview(),
  public.dashboard_project_overview(uuid, integer)
  from public, anon;
grant execute on function public.dashboard_create_workspace(text, text),
  public.dashboard_add_api_key(uuid, text, text, text),
  public.dashboard_revoke_api_key(uuid),
  public.dashboard_resolve_review(uuid, boolean, text),
  public.dashboard_update_project(uuid, text[], boolean, real, integer, integer),
  public.dashboard_is_super_admin(),
  public.dashboard_admin_overview(),
  public.dashboard_project_overview(uuid, integer)
  to authenticated;
