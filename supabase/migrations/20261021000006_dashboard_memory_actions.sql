-- Phase 12c: owners and admins can take a playbook out of service from the dashboard.
-- Quarantine sends it to the review queue (approving it there is the only way back to
-- active, so the promotion guard still applies); retire also closes its open reviews.

create function public.dashboard_set_playbook_status(
  p_playbook_id uuid, p_status text, p_note text
) returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  v_project_id uuid;
  v_who text := coalesce(auth.jwt() ->> 'email', auth.uid()::text);
  v_note text := nullif(trim(coalesce(p_note, '')), '');
begin
  select project_id into v_project_id from public.playbooks where id = p_playbook_id;
  perform access.require_project_admin(v_project_id);
  if p_status not in ('quarantined', 'retired') then
    raise exception 'status must be quarantined or retired' using errcode = 'invalid_parameter_value';
  end if;
  update public.playbooks set status = p_status where id = p_playbook_id;
  if p_status = 'quarantined' then
    insert into public.review_queue (project_id, object_type, object_id, reason)
    select v_project_id, 'playbook', p_playbook_id,
           'quarantined by ' || v_who || coalesce(': ' || left(v_note, 500), '')
     where not exists (select 1 from public.review_queue
                        where object_id = p_playbook_id and status = 'open');
  else
    update public.review_queue
       set status = 'rejected', reviewer = v_who, resolved_at = now(),
           resolution_note = coalesce(left(v_note, 1000), 'retired')
     where object_id = p_playbook_id and status = 'open';
  end if;
end
$$;

revoke all on function public.dashboard_set_playbook_status(uuid, text, text) from public, anon;
grant execute on function public.dashboard_set_playbook_status(uuid, text, text) to authenticated;
