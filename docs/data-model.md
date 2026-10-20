# Data model (Supabase Postgres + pgvector)

All tables carrying customer data have `project_id` and row-level security (RLS) policies. The server runs each request as the `retrack_api` role with `app.project_id` set for the transaction; RLS exposes only that project's rows. Supabase's `anon` and `authenticated` roles have no access until dashboard login is decided. API keys are checked by `private.verify_api_key`, the only path from `retrack_api` to `api_keys`. Vectors are `extensions.halfvec(1536)` (gemini-embedding-001 at 1,536 dimensions, half precision), cosine distance, HNSW indexes. Memory tables are written only by role `retrack_pipeline` inside one project (`pipeline_scope`); `retrack_api` has no access to them yet (recall in Phase 6 will add read access). Ask before creating migrations.

## Tenancy and access
| Table | Key fields |
|---|---|
| organizations | id, name, created_at |
| projects | id, org_id, name, region, retention_days, trusted_tools text[], task_trusted bool, holdout_rate (default 0.10), created_at |
| agents | id, project_id, name, framework (e.g. langgraph), recall_threshold (default 0.72), created_at |
| api_keys | id, project_id, prefix (shown to user, e.g. `rtk_live_ab12`), key_hash, name, created_at, last_used_at, revoked_at |
| members | org_id, user_id, role |

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
| playbooks | id, project_id, agent_id, version, status (candidate / active / quarantined / retired), title, task_pattern, preconditions, steps jsonb [{action, tool}], pitfalls, embedding halfvec(1536), embedding_model, support_count, trusted_support, untrusted_sources, quarantined_sources, passed_automatic_checks, uses, successes, success_rate, last_success_at, validated_models text[], tool_versions jsonb, content_hash, approved_by, approved_at, search_text tsvector, created_at, updated_at. A trigger refuses `active` unless `private.playbook_can_activate` (the promotion rule) holds |
| playbook_versions | project_id, playbook_id, version, snapshot jsonb, change_reason, created_at (for diff and rollback) |
| failure_signatures | id, project_id, agent_id, tool_name, error_class, input_shape (keys and types, no values), fingerprint (sha256 of tool, error class, input shape; unique per project), occurrences, first_seen, last_seen, example_run_id, recovery_playbook_id, unrecoverable bool |
| provenance | project_id, object_type, object_id, source_run_ids uuid[], input_sources text[] (tools used), trust_level (worst of the sources), reviewer_id, approved_at |
| review_queue | id, project_id, object_type, object_id, reason, status (open / approved / rejected), created_at, resolved_at |
| embedding_cache | project_id, model, content_hash, embedding (never embed the same text twice) |

## Recall
| Table | Key fields |
|---|---|
| recalls | id, project_id, agent_id, run_id, playbook_ids uuid[], warning_ids uuid[], holdout, mode (hybrid / keyword / holdout / no_agent), latency_ms, created_at |

At ingest a run is linked to the recalls made for its id (`runs.recalled_playbook_ids`, `runs.holdout`). After scoring, the learning loop updates the recalled playbooks' `uses`, `successes`, `success_rate` once per outcome (`runs.recall_counted_as`). `retrack_api` can read only `active` playbooks.

## Testing and migration
| Table | Key fields |
|---|---|
| eval_cases | id, project_id, source (playbook / failure), source_id, input jsonb, expected_assertions jsonb, last_result, last_model_id, last_run_at |
| migration_reports | id, project_id, from_model, to_model, status, summary jsonb, created_at |

## Usage metering
| Table | Key fields |
|---|---|
| usage_daily | project_id, day, runs_captured, recalls_served, distillations, tokens_processed, llm_input_tokens, llm_output_tokens (Retrack's own LLM spend) (primary key: project_id + day) |

Increment with an upsert. Raw `runs` rows (with timestamps) let usage history be rebuilt if metering changes later, so keep them for the project's retention period.

## Indexes
- HNSW index on `playbooks.embedding` and `runs.task_embedding` (cosine).
- Full-text (tsvector) index on `playbooks.preconditions || pitfalls` and `runs.task_text` for hybrid search.
- B-tree on `(project_id, agent_id, status)` for playbooks; `(project_id, created_at)` for runs.
