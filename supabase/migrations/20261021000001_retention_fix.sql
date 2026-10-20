-- enforce_retention without a temporary table, so it can run more than once per
-- transaction (manual re-runs, tests).
create or replace function private.enforce_retention() returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_runs integer;
  v_recalls integer;
  v_results integer;
begin
  with expired as (
    select r.project_id, r.id
      from public.runs r join public.projects p on p.id = r.project_id
     where r.created_at < now() - make_interval(days => p.retention_days)
       and not exists (
         select 1 from public.provenance pv
           join public.playbooks pb on pb.id = pv.object_id and pb.project_id = pv.project_id
          where pv.project_id = r.project_id and pv.object_type = 'playbook'
            and pb.status <> 'retired' and r.id = any(pv.source_run_ids))
  ),
  findings as (
    delete from public.firewall_findings f using expired e
     where f.project_id = e.project_id and f.object_type = 'run' and f.object_id = e.id
  )
  delete from public.runs r using expired e
   where r.project_id = e.project_id and r.id = e.id;
  get diagnostics v_runs = row_count;

  delete from public.recalls r using public.projects p
   where p.id = r.project_id and r.created_at < now() - make_interval(days => p.retention_days);
  get diagnostics v_recalls = row_count;
  delete from public.eval_results r using public.projects p
   where p.id = r.project_id and r.created_at < now() - make_interval(days => p.retention_days);
  get diagnostics v_results = row_count;
  delete from public.embedding_cache c using public.projects p
   where p.id = c.project_id and c.created_at < now() - make_interval(days => p.retention_days);
  delete from public.ingest_counters where window_start < now() - interval '1 day';
  delete from pgmq.q_runs_dlq where enqueued_at < now() - interval '30 days';

  return jsonb_build_object('runs', v_runs, 'recalls', v_recalls, 'eval_results', v_results);
end
$$;
