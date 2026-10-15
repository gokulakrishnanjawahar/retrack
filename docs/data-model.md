# Data model (Supabase Postgres + pgvector)

All tables carrying customer data have `project_id` and row-level security (RLS) policies. Vector dimension depends on the embedding model, which is OPEN; write `vector(<DIM>)` as a placeholder until decided. Ask before creating migrations.

## Tenancy and access
| Table | Key fields |
|---|---|
| organizations | id, name, created_at |
| projects | id, org_id, name, region, retention_days, created_at |
| agents | id, project_id, name, framework (e.g. langgraph), created_at |
| api_keys | id, project_id, prefix (shown to user, e.g. `rtk_live_ab12`), key_hash, name, created_at, last_used_at, revoked_at |
| members | org_id, user_id, role |

API keys: generate a random secret, show it once, store only a hash (e.g. SHA-256 with a server-side pepper) plus a short prefix for lookup. Support revoke and rotate.

## Runs
| Table | Key fields |
|---|---|
| runs | id (client-generated, idempotency key), project_id, agent_id, task_text, task_embedding vector(<DIM>), model_id, tool_versions jsonb, outcome (success / failure / unknown), outcome_source (test / feedback / event / judge), confidence, tokens_in, tokens_out, cost_usd, latency_ms, taint_level (trusted / untrusted / quarantined), holdout bool, recalled_playbook_ids uuid[], trace_uri, created_at |
| steps | run_id, idx, type (llm / tool), tool_name, args_hash, args_redacted jsonb, result_class, error_class, latency_ms, tokens_in, tokens_out, input_trust (trusted / untrusted) |

## Memory
| Table | Key fields |
|---|---|
| playbooks | id, project_id, agent_id, version, status (candidate / active / quarantined / retired), preconditions text, steps jsonb, pitfalls text, embedding vector(<DIM>), success_rate, uses, last_success_at, validated_models text[], tool_versions jsonb, content_hash, created_at |
| playbook_versions | playbook_id, version, snapshot jsonb, change_reason, created_at (for diff and rollback) |
| failure_signatures | id, project_id, agent_id, tool_name, error_class, input_shape, fingerprint (unique per project), occurrences, last_seen, recovery_playbook_id, unrecoverable bool |
| provenance | object_type, object_id, source_run_ids uuid[], input_sources text[], trust_level, reviewer_id, approved_at |
| review_queue | id, project_id, object_type, object_id, reason, status, created_at |

## Testing and migration
| Table | Key fields |
|---|---|
| eval_cases | id, project_id, source (playbook / failure), source_id, input jsonb, expected_assertions jsonb, last_result, last_model_id, last_run_at |
| migration_reports | id, project_id, from_model, to_model, status, summary jsonb, created_at |

## Usage metering
| Table | Key fields |
|---|---|
| usage_daily | project_id, day, runs_captured, recalls_served, distillations, tokens_processed (primary key: project_id + day) |

Increment with an upsert. Raw `runs` rows (with timestamps) let usage history be rebuilt if metering changes later, so keep them for the project's retention period.

## Indexes
- HNSW index on `playbooks.embedding` and `runs.task_embedding` (cosine).
- Full-text (tsvector) index on `playbooks.preconditions || pitfalls` and `runs.task_text` for hybrid search.
- B-tree on `(project_id, agent_id, status)` for playbooks; `(project_id, created_at)` for runs.
