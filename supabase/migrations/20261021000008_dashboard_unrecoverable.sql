-- Phase 12 audit: owners and admins can override a failure signature's circuit breaker from
-- the dashboard (same rule as `retrack-admin set-unrecoverable`); null returns to automatic
-- (5+ occurrences and never recovered).

create function public.dashboard_set_unrecoverable(p_signature_id uuid, p_value boolean)
returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  v_project_id uuid;
begin
  select project_id into v_project_id from public.failure_signatures where id = p_signature_id;
  perform access.require_project_admin(v_project_id);
  update public.failure_signatures
     set unrecoverable_override = p_value,
         unrecoverable = coalesce(p_value, occurrences >= 5 and recoveries = 0)
   where id = p_signature_id;
end
$$;

revoke all on function public.dashboard_set_unrecoverable(uuid, boolean) from public, anon;
grant execute on function public.dashboard_set_unrecoverable(uuid, boolean) to authenticated;
