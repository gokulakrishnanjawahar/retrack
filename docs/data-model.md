# Data model (Supabase Postgres + pgvector)

All tables carrying customer data have `project_id` and row-level security (RLS) policies. The server runs each request as the `retrack_api` role with `app.project_id` set for the transaction; RLS exposes only that project's rows. Supabase's `anon` role has no access. Dashboard users (`authenticated`, Supabase Auth) may only READ rows of projects whose organization they belong to (policies `dashboard_members_read`, helpers in schema `access`); they cannot write tables directly and change things only through role-checked `public.dashboard_*` functions (owner or admin). They see an API key's prefix and dates, never its hash. API keys are checked by `private.verify_api_key`, the only path from `retrack_api` to `api_keys`. Vectors are `extensions.halfvec(1536)` (gemini-embedding-001 at 1,536 dimensions, half precision), cosine distance, HNSW indexes. Memory tables are written only by role `retrack_pipeline` inside one project (`pipeline_scope`); `retrack_api` has no access to them yet (recall in Phase 6 will add read access). Ask before creating migrations.

## Tenancy and access
| Table | Key fields |
|---|---|
| organizations | id, name, created_at |
| projects | id, org_id, name, region, retention_days, trusted_tools text[], task_trusted bool, holdout_rate (default 0.10), created_at |
| agents | id, project_id, name, framework (e.g. langgraph), recall_threshold (default 0.72), created_at |
| api_keys | id, project_id, prefix (shown to user, e.g. `rtk_live_ab12`), key_hash, name, created_at, last_used_at, revoked_at |
| members | org_id, user_id (→ auth.users), role (owner / admin / member) |
| super_admins | user_id (→ auth.users). Cross-project analytics in the dashboard; Gokul only. Granted with `retrack-admin set-super-admin` |

API keys: format `rtk_live_<48 hex>` (or `rtk_test_`); show once; store only HMAC-SHA256(pepper, secret) plus a prefix (`rtk_live_` + 8 chars) for lookup. Pepper is `RETRACK_KEY_PEPPER`. Support revoke and rotate. Project defaults: `retention_days` 90, `region` ap-south-1.

## Runs
| Table | Key fields |
|---|---|
| runs | id (client-generated, idempotency key; primary key is (project_id, id) so tenants never collide), project_id, agent_id, task_text, task_embedding halfvec(1536), embedding_model, distilled_at, distilled_as (success / failure / skipped), model_id, tool_versions jsonb, outcome (success / failure / unknown), outcome_source (test / feedback / event / judge), confidence, tokens_in, tokens_out, cost_usd, latency_ms, taint_level (trusted / untrusted / quarantined), holdout bool, recalled_playbook_ids uuid[], trace_uri, output_text (final answer, redacted, at most 4,000 characters), processed_at (set by the firewall worker), created_at |
| steps | project_id, run_id, idx (primary key: project_id + run_id + idx), type (llm / tool), tool_name, args_hash, args_redacted jsonb, result_class, error_class, latency_ms, tokens_in, tokens_out, input_trust (trusted / untrusted) |

## Outcomes
| Table | Key fields |
|---|---|
| outcome_signals | id, project_id, run_id, source (test / event / feedback / judge), outcome (success / failure), confidence, detail jsonb (redacted; judge stores its reason and model), seq (insertion order), created_at |

`runs.outcome / outcome_source / confidence` hold the winning signal (see `api.md`, Feedback).

## Queues (pgmq)
| Queue | Message |
|---|---|
| runs | `{project_id, run_id}`, one per newly ingested run; added only via `private.enqueue_run` (role `retrack_api`) |
| runs_dlq | a `runs` message plus `error` and `failed_at`, after 5 failed attempts |

Only role `retrack_worker` can read or remove `runs` jobs (`private.read_run_jobs`, `complete_run_job`, `dead_letter_run_job`). The server login `retrack_server` can switch to `retrack_api` or `retrack_worker`, nothing else.

## Memory
| Table | Key fields |
|---|---|
| playbooks | id, project_id, agent_id, version, status (candidate / active / quarantined / retired), title, task_pattern, preconditions, steps jsonb [{action, tool}], pitfalls, embedding halfvec(1536), embedding_model, support_count, trusted_support, untrusted_sources, quarantined_sources, passed_automatic_checks, uses, successes, success_rate, last_success_at, validated_models text[], tool_versions jsonb, content_hash, approved_by, approved_at, origin_playbook_id (the playbook a shared copy or update came from), search_text tsvector, created_at, updated_at. A trigger refuses `active` unless `private.playbook_can_activate` (the promotion rule) holds |
| playbook_versions | project_id, playbook_id, version, snapshot jsonb, change_reason, embedding, embedding_model, created_at (for diff and rollback; the embedding is restored with the content) |
| playbook_proposals | id, project_id, source_playbook_id, source_version, target_agent_id, target_playbook_id (null = new playbook), target_version, snapshot jsonb, checks jsonb [{check, detail}], status (open / approved / rejected), proposed_by, note, reviewer, resolution_note, result_playbook_id, created_at, resolved_at. One open proposal per source and target agent. Fleet sharing (Phase 13) |
| failure_signatures | id, project_id, agent_id, tool_name, error_class, input_shape (keys and types, no values), fingerprint (sha256 of tool, error class, input shape; unique per project), occurrences, first_seen, last_seen, example_run_id, recovery_playbook_id, recovery_steps jsonb, recoveries, unrecoverable bool (automatic unless unrecoverable_override) |
| provenance | project_id, object_type, object_id, source_run_ids uuid[], input_sources text[] (tools used), trust_level (worst of the sources), reviewer_id, approved_at |
| review_queue | id, project_id, object_type, object_id, reason, status (open / approved / rejected), reviewer, resolution_note, created_at, resolved_at |
| firewall_findings | id, project_id, object_type (run / playbook), object_id, check_name (injection_heuristic / injection_classifier / anomaly / instruction_shaped), severity (flag / block), detail, created_at |
| embedding_cache | project_id, model, content_hash, embedding (never embed the same text twice) |

## Recall
| Table | Key fields |
|---|---|
| recalls | id, project_id, agent_id, run_id, playbook_ids uuid[], warning_ids uuid[], holdout, mode (hybrid / keyword / holdout / no_agent), latency_ms, created_at |

At ingest a run is linked to the recalls made for its id (`runs.recalled_playbook_ids`, `runs.holdout`). After scoring, the learning loop updates the recalled playbooks' `uses`, `successes`, `success_rate` once per outcome (`runs.recall_counted_as`). `retrack_api` can read only `active` playbooks.

## Testing and migration
| Table | Key fields |
|---|---|
| eval_cases | id, project_id, agent_id, source (playbook / failure), source_id, source_version, input jsonb, expected_assertions jsonb, critical, status (active / retired), last_result (passed / failed), last_model_id, last_run_at, created_at. Created and retired by triggers |
| eval_results | id, project_id, eval_case_id, test_run_id, passed, model_id, details jsonb ({failures, completed}), migration_id, created_at |
| migration_reports | id, project_id, agent_id, from_model, to_model, model_applied, status (running / completed), summary jsonb, created_at, completed_at |

## Usage metering
| Table | Key fields |
|---|---|
| usage_daily | project_id, day, runs_captured, recalls_served, distillations, tokens_processed, llm_input_tokens, llm_output_tokens (Retrack's own LLM spend) (primary key: project_id + day) |

Increment with an upsert.

## Dashboard functions
Called by the dashboard as the signed-in user (Supabase RPC). Quarantine and retire share one rule, `private.set_playbook_status`, with `PATCH /v1/playbooks/{id}` (which runs it in `pipeline_scope`). Regression cases follow new versions of active playbooks. Each checks the caller's role in the database: `dashboard_create_workspace` (organization + project, caller becomes owner), `dashboard_add_api_key` (the dashboard server generates the key and its HMAC with the pepper; only prefix and hash reach the database), `dashboard_revoke_api_key`, `dashboard_update_project` (trust, holdout, retention, rate limit), `dashboard_resolve_review`, `dashboard_set_playbook_status` (quarantine, which reopens review, or retire; never activate), `dashboard_set_unrecoverable` (force or reset a failure's circuit breaker), `dashboard_propose_playbook`, `dashboard_resolve_proposal` and `dashboard_rollback_playbook` (fleet sharing and rollback, owner or admin), `dashboard_is_super_admin`, `dashboard_admin_overview` (super admins only: users, organizations, runs per day across projects, usage, queue depth, dead letters, last run of each Supabase Cron job), `dashboard_admin_project_stats(days)` (super admins only: per project runs, success rate, memory lift vs holdout, recall hit rate, agent tokens and cost, Retrack LLM tokens, memory counts, last run; also the source of the `/admin/export` CSV, whose text cells are protected against spreadsheet formulas). `runs` is in the `supabase_realtime` publication so the dashboard streams new runs live; RLS applies to Realtime too. Raw `runs` rows (with timestamps) let usage history be rebuilt if metering changes later, so keep them for the project's retention period.

## Indexes
- HNSW index on `playbooks.embedding` and `runs.task_embedding` (cosine).
- Full-text (tsvector) index on `playbooks.preconditions || pitfalls` and `runs.task_text` for hybrid search.
- B-tree on `(project_id, agent_id, status)` for playbooks; `(project_id, created_at)` for runs.
