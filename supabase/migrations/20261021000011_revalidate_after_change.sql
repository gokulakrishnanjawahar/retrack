-- Phase 13 audit: an approved update or a rollback replaces a playbook's steps, so its model
-- validation no longer applies. Clearing validated_models keeps plan replay (which replays the
-- exact steps, docs/recall-gating.md) off until `retrack migrate` validates the new content.

create or replace function public.dashboard_resolve_proposal(
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
  if v_source.status <> 'active' then
    raise exception 'the shared playbook is no longer active; reject this proposal'
      using errcode = 'invalid_parameter_value';
  end if;
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
           origin_playbook_id = v_p.source_playbook_id,
           validated_models = '{}'
     where id = v_result;
  end if;

  -- The approved content replaces whatever was waiting for review on the target.
  update public.review_queue
     set status = 'approved', reviewer = v_reviewer, resolved_at = now(),
         resolution_note = 'superseded by fleet proposal ' || p_proposal_id
   where project_id = v_p.project_id and object_id = v_result and status = 'open';

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

create or replace function public.dashboard_rollback_playbook(p_playbook_id uuid, p_version integer, p_note text)
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
         version = v_pb.version + 1,
         validated_models = '{}'
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
