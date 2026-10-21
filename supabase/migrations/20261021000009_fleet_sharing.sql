-- Phase 13: fleet sharing (docs/features.md block K) and playbook rollback.
--
--   * playbook_proposals: an owner or admin proposes an ACTIVE playbook of one agent to another
--     agent of the same project, as a new playbook or as an update of one of that agent's
--     playbooks. Nothing changes until an owner or admin approves; approval records them as
--     the reviewer (human review, CLAUDE.md rule 8).
--   * playbook_versions keep each version's embedding, so a rollback (or an approved proposal)
--     restores content and its embedding together, without re-embedding.
--   * playbooks.origin_playbook_id: the playbook a shared copy or update came from.
--   * private.set_playbook_status: the one rule for quarantine and retire, used by the
--     dashboard and by PATCH /v1/playbooks/{id} (API keys may only take memory out of service).
--   * Regression cases follow new versions of active playbooks (not only status changes).

alter table public.playbook_versions
  add column embedding extensions.halfvec(1536),
  add column embedding_model text;

update public.playbook_versions v
   set embedding = p.embedding, embedding_model = p.embedding_model
  from public.playbooks p
 where p.id = v.playbook_id and p.version = v.version;

alter table public.playbooks
  add column origin_playbook_id uuid references public.playbooks (id) on delete set null;

create table public.playbook_proposals (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects (id) on delete cascade,
  source_playbook_id uuid not null,
  source_version integer not null,
  target_agent_id uuid not null,
  target_playbook_id uuid,
  target_version integer,
  snapshot jsonb not null,
  checks jsonb not null default '[]',
  status text not null default 'open'
    check (status in ('open', 'approved', 'rejected')),
  proposed_by text not null,
  note text,
  reviewer text,
  resolution_note text,
  result_playbook_id uuid,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  foreign key (source_playbook_id, project_id) references public.playbooks (id, project_id)
    on delete cascade,
  foreign key (target_playbook_id, project_id) references public.playbooks (id, project_id)
    on delete cascade,
  foreign key (target_agent_id, project_id) references public.agents (id, project_id)
    on delete cascade
);

create index playbook_proposals_open_idx on public.playbook_proposals (project_id, status);
create unique index playbook_proposals_one_open_idx
  on public.playbook_proposals (source_playbook_id, target_agent_id) where status = 'open';

alter table public.playbook_proposals enable row level security;
revoke all on public.playbook_proposals from anon, authenticated;
grant select on public.playbook_proposals to authenticated;
create policy dashboard_members_read on public.playbook_proposals for select to authenticated
  using (project_id in (select access.my_project_ids()));

-- Quarantine and retire --------------------------------------------------------------------

-- Runs as the caller: the dashboard function (owner) or the API in pipeline_scope (RLS keeps
-- it inside the key's project). Returns the new status, or null if the playbook is not found.
create function private.set_playbook_status(
  p_project_id uuid, p_playbook_id uuid, p_status text, p_who text, p_note text
) returns text
language plpgsql
set search_path = ''
as $$
declare
  v_note text := nullif(trim(coalesce(p_note, '')), '');
begin
  if p_status not in ('quarantined', 'retired') then
    raise exception 'status must be quarantined or retired' using errcode = 'invalid_parameter_value';
  end if;
  update public.playbooks set status = p_status
   where project_id = p_project_id and id = p_playbook_id;
  if not found then
    return null;
  end if;
  if p_status = 'quarantined' then
    insert into public.review_queue (project_id, object_type, object_id, reason)
    select p_project_id, 'playbook', p_playbook_id,
           'quarantined by ' || p_who || coalesce(': ' || left(v_note, 500), '')
     where not exists (select 1 from public.review_queue
                        where project_id = p_project_id and object_id = p_playbook_id
                          and status = 'open');
  else
    update public.review_queue
       set status = 'rejected', reviewer = p_who, resolved_at = now(),
           resolution_note = coalesce(left(v_note, 1000), 'retired')
     where project_id = p_project_id and object_id = p_playbook_id and status = 'open';
  end if;
  return p_status;
end
$$;

revoke all on function private.set_playbook_status(uuid, uuid, text, text, text)
  from public, anon, authenticated;
grant execute on function private.set_playbook_status(uuid, uuid, text, text, text)
  to retrack_pipeline;

create or replace function public.dashboard_set_playbook_status(
  p_playbook_id uuid, p_status text, p_note text
) returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  v_project_id uuid;
begin
  select project_id into v_project_id from public.playbooks where id = p_playbook_id;
  perform access.require_project_admin(v_project_id);
  perform private.set_playbook_status(
    v_project_id, p_playbook_id, p_status,
    coalesce(auth.jwt() ->> 'email', auth.uid()::text), p_note);
end
$$;

-- Proposals ---------------------------------------------------------------------------------

create function public.dashboard_propose_playbook(
  p_playbook_id uuid, p_target_agent_id uuid, p_target_playbook_id uuid, p_note text
) returns uuid
language plpgsql security definer
set search_path = ''
as $$
declare
  v_source public.playbooks;
  v_target_version integer;
  v_new_tools text[];
  v_checks jsonb := '[]';
  v_id uuid;
begin
  select * into v_source from public.playbooks where id = p_playbook_id;
  perform access.require_project_admin(v_source.project_id);
  if v_source.status <> 'active' then
    raise exception 'only active playbooks can be shared' using errcode = 'invalid_parameter_value';
  end if;
  if p_target_agent_id is null or p_target_agent_id = v_source.agent_id or not exists (
       select 1 from public.agents where id = p_target_agent_id and project_id = v_source.project_id) then
    raise exception 'choose another agent of this project' using errcode = 'invalid_parameter_value';
  end if;
  if p_target_playbook_id is not null then
    select version into v_target_version from public.playbooks
     where id = p_target_playbook_id and agent_id = p_target_agent_id
       and project_id = v_source.project_id and status <> 'retired';
    if v_target_version is null then
      raise exception 'the playbook to update must belong to the target agent'
        using errcode = 'invalid_parameter_value';
    end if;
  end if;
  if exists (select 1 from public.playbook_proposals
              where source_playbook_id = p_playbook_id and target_agent_id = p_target_agent_id
                and status = 'open') then
    raise exception 'this playbook is already proposed to that agent'
      using errcode = 'invalid_parameter_value';
  end if;

  -- Tools the playbook uses that the target agent has never called (shown to the reviewer).
  select array_agg(distinct t.tool order by t.tool) into v_new_tools
    from (select s ->> 'tool' as tool from jsonb_array_elements(v_source.steps) s
           where jsonb_typeof(s) = 'object' and coalesce(s ->> 'tool', '') not in ('', 'none')) t
   where not exists (
     select 1 from public.steps st
       join public.runs r on r.project_id = st.project_id and r.id = st.run_id
      where st.project_id = v_source.project_id and r.agent_id = p_target_agent_id
        and st.tool_name = t.tool);
  if v_new_tools is not null then
    v_checks := v_checks || jsonb_build_array(jsonb_build_object(
      'check', 'new_tools',
      'detail', 'tools this agent has never used: ' || array_to_string(v_new_tools, ', ')));
  end if;
  if v_source.untrusted_sources > 0 then
    v_checks := v_checks || jsonb_build_array(jsonb_build_object(
      'check', 'untrusted_sources',
      'detail', v_source.untrusted_sources || ' of its source runs used untrusted input'));
  end if;

  insert into public.playbook_proposals (project_id, source_playbook_id, source_version,
    target_agent_id, target_playbook_id, target_version, snapshot, checks, proposed_by, note)
  values (
    v_source.project_id, p_playbook_id, v_source.version, p_target_agent_id,
    p_target_playbook_id, v_target_version,
    jsonb_build_object('title', v_source.title, 'task_pattern', v_source.task_pattern,
      'preconditions', v_source.preconditions, 'steps', v_source.steps,
      'pitfalls', v_source.pitfalls),
    v_checks, coalesce(auth.jwt() ->> 'email', auth.uid()::text), left(p_note, 1000))
  returning id into v_id;
  return v_id;
end
$$;

create function public.dashboard_resolve_proposal(
  p_proposal_id uuid, p_approve boolean, p_note text
) returns uuid
language plpgsql security definer
set search_path = ''
as $$
declare
  v_p public.playbook_proposals;
  v_source public.playbooks;
  v_source_agent text;
  v_reviewer text := coalesce(auth.jwt() ->> 'email', auth.uid()::text);
  v_embedding extensions.halfvec;
  v_model text;
  v_hash text;
  v_reason text;
  v_result uuid;
  v_version integer;
begin
  select * into v_p from public.playbook_proposals where id = p_proposal_id;
  if not found then
    raise exception 'not found' using errcode = 'no_data_found';
  end if;
  perform access.require_project_admin(v_p.project_id);
  if v_p.status <> 'open' then
    raise exception 'already resolved' using errcode = 'invalid_parameter_value';
  end if;

  if not p_approve then
    update public.playbook_proposals
       set status = 'rejected', reviewer = v_reviewer, resolution_note = left(p_note, 1000),
           resolved_at = now()
     where id = p_proposal_id;
    return null;
  end if;

  select * into v_source from public.playbooks where id = v_p.source_playbook_id;
  select name into v_source_agent from public.agents where id = v_source.agent_id;
  -- The embedding of exactly the proposed version (the source may have changed since).
  select embedding, embedding_model into v_embedding, v_model from public.playbook_versions
   where playbook_id = v_p.source_playbook_id and version = v_p.source_version;
  if v_embedding is null and v_source.version = v_p.source_version then
    v_embedding := v_source.embedding;
    v_model := v_source.embedding_model;
  end if;
  v_hash := encode(extensions.digest(v_p.snapshot::text, 'sha256'), 'hex');
  v_reason := 'shared from ' || coalesce(v_source_agent, 'another agent') || ': proposed by '
              || v_p.proposed_by || ', approved by ' || v_reviewer;

  if v_p.target_playbook_id is null then
    v_result := gen_random_uuid();
    -- Provenance first, so the regression case created on insert finds a source run.
    insert into public.provenance (project_id, object_type, object_id, source_run_ids,
      input_sources, trust_level, reviewer_id, approved_at)
    select v_p.project_id, 'playbook', v_result, pv.source_run_ids, pv.input_sources,
           pv.trust_level, v_reviewer, now()
      from public.provenance pv
     where pv.project_id = v_p.project_id and pv.object_type = 'playbook'
       and pv.object_id = v_p.source_playbook_id;
    if not found then
      insert into public.provenance (project_id, object_type, object_id, trust_level,
        reviewer_id, approved_at)
      values (v_p.project_id, 'playbook', v_result, 'untrusted', v_reviewer, now());
    end if;
    insert into public.playbooks (id, project_id, agent_id, status, title, task_pattern,
      preconditions, steps, pitfalls, embedding, embedding_model, support_count,
      untrusted_sources, passed_automatic_checks, tool_versions, content_hash, confidence,
      approved_by, approved_at, origin_playbook_id)
    values (
      v_result, v_p.project_id, v_p.target_agent_id, 'active', v_p.snapshot ->> 'title',
      coalesce(v_p.snapshot ->> 'task_pattern', ''), coalesce(v_p.snapshot ->> 'preconditions', ''),
      coalesce(v_p.snapshot -> 'steps', '[]'), coalesce(v_p.snapshot ->> 'pitfalls', ''),
      v_embedding, v_model, 1, v_source.untrusted_sources, v_source.passed_automatic_checks,
      v_source.tool_versions, v_hash, v_source.confidence, v_reviewer, now(),
      v_p.source_playbook_id);
    v_version := 1;
  else
    select version into v_version from public.playbooks where id = v_p.target_playbook_id;
    if v_version is distinct from v_p.target_version then
      raise exception 'the target playbook changed after this proposal; propose again'
        using errcode = 'invalid_parameter_value';
    end if;
    v_version := v_version + 1;
    v_result := v_p.target_playbook_id;
    update public.playbooks
       set title = v_p.snapshot ->> 'title',
           task_pattern = coalesce(v_p.snapshot ->> 'task_pattern', ''),
           preconditions = coalesce(v_p.snapshot ->> 'preconditions', ''),
           steps = coalesce(v_p.snapshot -> 'steps', '[]'),
           pitfalls = coalesce(v_p.snapshot ->> 'pitfalls', ''),
           embedding = coalesce(v_embedding, embedding),
           embedding_model = case when v_embedding is null then embedding_model else v_model end,
           content_hash = v_hash, version = v_version, status = 'active',
           approved_by = v_reviewer, approved_at = now(),
           origin_playbook_id = v_p.source_playbook_id
     where id = v_result;
  end if;

  insert into public.playbook_versions (project_id, playbook_id, version, snapshot,
    change_reason, embedding, embedding_model)
  select v_p.project_id, v_result, v_version, v_p.snapshot, v_reason, p.embedding,
         p.embedding_model
    from public.playbooks p where p.id = v_result;

  update public.playbook_proposals
     set status = 'approved', reviewer = v_reviewer, resolution_note = left(p_note, 1000),
         resolved_at = now(), result_playbook_id = v_result
   where id = p_proposal_id;
  return v_result;
end
$$;

-- Rollback ----------------------------------------------------------------------------------

create function public.dashboard_rollback_playbook(p_playbook_id uuid, p_version integer, p_note text)
returns integer
language plpgsql security definer
set search_path = ''
as $$
declare
  v_pb public.playbooks;
  v_row public.playbook_versions;
  v_who text := coalesce(auth.jwt() ->> 'email', auth.uid()::text);
  v_note text := nullif(trim(coalesce(p_note, '')), '');
begin
  select * into v_pb from public.playbooks where id = p_playbook_id;
  perform access.require_project_admin(v_pb.project_id);
  if p_version = v_pb.version then
    raise exception 'the playbook is already at this version' using errcode = 'invalid_parameter_value';
  end if;
  select * into v_row from public.playbook_versions
   where playbook_id = p_playbook_id and version = p_version;
  if not found then
    raise exception 'version not found' using errcode = 'no_data_found';
  end if;
  update public.playbooks
     set title = coalesce(v_row.snapshot ->> 'title', title),
         task_pattern = coalesce(v_row.snapshot ->> 'task_pattern', ''),
         preconditions = coalesce(v_row.snapshot ->> 'preconditions', ''),
         steps = coalesce(v_row.snapshot -> 'steps', '[]'),
         pitfalls = coalesce(v_row.snapshot ->> 'pitfalls', ''),
         embedding = coalesce(v_row.embedding, embedding),
         embedding_model = case when v_row.embedding is null then embedding_model
                                else v_row.embedding_model end,
         content_hash = encode(extensions.digest(v_row.snapshot::text, 'sha256'), 'hex'),
         version = v_pb.version + 1
   where id = p_playbook_id;
  insert into public.playbook_versions (project_id, playbook_id, version, snapshot,
    change_reason, embedding, embedding_model)
  select v_pb.project_id, p_playbook_id, v_pb.version + 1, v_row.snapshot,
         'rolled back to v' || p_version || ' by ' || v_who || coalesce(': ' || left(v_note, 500), ''),
         p.embedding, p.embedding_model
    from public.playbooks p where p.id = p_playbook_id;
  return v_pb.version + 1;
end
$$;

revoke all on function public.dashboard_propose_playbook(uuid, uuid, uuid, text),
  public.dashboard_resolve_proposal(uuid, boolean, text),
  public.dashboard_rollback_playbook(uuid, integer, text)
  from public, anon;
grant execute on function public.dashboard_propose_playbook(uuid, uuid, uuid, text),
  public.dashboard_resolve_proposal(uuid, boolean, text),
  public.dashboard_rollback_playbook(uuid, integer, text)
  to authenticated;

-- Regression cases follow new versions ---------------------------------------------------

create or replace function private.sync_playbook_eval_case() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.status = 'active' and (tg_op = 'INSERT' or old.status is distinct from 'active'
                                or old.version is distinct from new.version) then
    insert into public.eval_cases
      (project_id, agent_id, source, source_id, source_version, input, expected_assertions)
    values (
      new.project_id,
      new.agent_id,
      'playbook',
      new.id,
      new.version,
      jsonb_build_object('task', coalesce(
        (select r.task_text from public.provenance pv
           join public.runs r on r.project_id = pv.project_id and r.id = pv.source_run_ids[1]
          where pv.project_id = new.project_id and pv.object_type = 'playbook'
            and pv.object_id = new.id),
        nullif(new.task_pattern, ''),
        new.title)),
      jsonb_build_array(
        jsonb_build_object('type', 'completes'),
        jsonb_build_object('type', 'tool_sequence', 'tools', coalesce(
          (select jsonb_agg(s -> 'tool') from jsonb_array_elements(new.steps) s
            where coalesce(s ->> 'tool', '') not in ('', 'none')),
          '[]'::jsonb)))
    )
    on conflict (project_id, source, source_id) do update
      set status = 'active',
          source_version = excluded.source_version,
          input = excluded.input,
          expected_assertions = excluded.expected_assertions;
  elsif tg_op = 'UPDATE' and old.status = 'active' and new.status <> 'active' then
    update public.eval_cases set status = 'retired'
     where project_id = new.project_id and source = 'playbook' and source_id = new.id;
  end if;
  return new;
end
$$;

drop trigger playbooks_sync_eval_case on public.playbooks;
create trigger playbooks_sync_eval_case
  after insert or update of status, version on public.playbooks
  for each row execute function private.sync_playbook_eval_case();
