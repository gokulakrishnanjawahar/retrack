# Regression tests and model migration

## Memory doubles as tests
- Every new **active playbook** generates an eval case: representative input + assertions describing a successful outcome.
- Every new **failure signature** generates an eval case asserting the failure no longer happens (or the known recovery is applied).
- Eval cases are stored in `eval_cases` and versioned with their source.

## Regression runner
- CLI: `retrack test` runs the project's eval cases against the customer's agent (customer provides an entry point that runs one task).
- GitHub Action wraps the CLI and fails the check when pass rate drops below a threshold or any previously passing critical case fails.
- Results are written back (`last_result`, `last_model_id`, `last_run_at`).
- Assertions support: exact/structured match, tool-call expectations (which tools, in what order), and LLM-judged criteria for open-ended outputs.

## As built (Phase 9)
- **Cases are created by database triggers:** a playbook becoming `active` gets a case (input: the task of its first source run; assertions: `completes` and `tool_sequence` of its steps' tools); retiring it retires the case; a failure signature reaching 2 occurrences gets a **critical** case asserting `no_failure` of that tool and error class.
- **Assertion types:** `completes` (the entry point did not raise), `tool_sequence` (tools called in this order, other calls allowed in between), `no_failure` (that tool did not fail with that error class), `output_contains`. Unknown types are skipped, not failed. **AI-judged criteria are deferred** until customers can bring their own LLM key (decided 2026-10-20).
- **`retrack test --entry module:function --agent NAME [--threshold 0.9] [--model-id M]`**: the entry is `run_task(task: str, callbacks: list) -> str` and must pass `callbacks` to the agent. Runs made by the command are never sent as runs; only results go to `POST /v1/eval-results`. Exit 0 = pass, 1 = pass rate below threshold or a critical case that passed last time now fails, 2 = usage or connection error.
- **GitHub Action for customers:** `sdk/github-action/action.yml` (composite; inputs reach the shell only via environment variables) with `example-workflow.yml`. Publishing it needs a public repository.

## Model migration
Triggered by `POST /v1/migrations` with a target model.
1. Replay all eval cases (or a sampled set) on the target model.
2. Produce a per-playbook report: still passes / needs re-learning / breaks.
3. Playbooks that pass are tagged with the new model in `validated_models`.
4. Failures produce a list of affected playbooks and failure cases for the developer to fix before switching.

Purpose: model providers deprecate models on fixed timelines, and newer models do not always behave the same on specific task types. Migration should become a checklist, not a scramble.

## Model migration as built (Phase 10)
- `retrack migrate --to NEW [--from OLD] --entry module:function --agent NAME [--sample N --seed S]` runs on the customer's side (their agent, their model keys; $0 for Retrack). It opens a report (`POST /v1/migrations`), replays the eval cases with `run_task(task, callbacks, model_id)` (a two-argument entry still runs, with a warning and `model_applied = false`), posts results with the `migration_id`, then prints the report from `GET /v1/migrations/{id}`.
- Classification: playbook case passed -> `passes` (the model is added to the playbook's `validated_models`, so recall's version match becomes 1.0 on it); completed but an assertion failed -> `needs_relearning`; raised -> `breaks`. Failure case passed -> `fixed`, else `returns`.
- Exit 1 when anything `breaks` or a known failure `returns`, so the command can gate a model switch in CI.
- Migration results never change `eval_cases.last_result`, which tracks the current model.
- `retrack test --model-id M` also passes the model to three-argument entry functions.

## Error fingerprinting and known-fix recovery
- Fingerprint = hash of (tool_name, error_class, normalised input shape).
- When a live failure matches a known fingerprint with a recovery playbook, the SDK can surface the recovery instead of blind retry.
- When a fingerprint is marked `unrecoverable`, the SDK's circuit-breaker stops retries early.

## Recovery and circuit breaker as built (Phase 11)
- **Learning fixes (server, no LLM):** in a successful run, a tool step that failed and a later successful call of the same tool make a recovery: the successful tool calls in between, then the retry (e.g. "call check_delivery, then retry refunds_api"). Stored on the failure signature (`recovery_steps`, `recoveries`), once per run. Works with embeddings off.
- **Unrecoverable:** automatically true after 5+ occurrences with no recovery ever recorded; a recorded recovery clears it. `retrack-admin set-unrecoverable --signature-id ID --value true|false|auto` overrides.
- **Recall warnings** carry `fingerprint`, `recovery`, `recovery_steps`, `unrecoverable`; signatures with a known fix are warned about even before they recur.
- **SDK:** `memory.protect(tools, max_same_failure=3)` wraps LangChain tools. A known failure returns its fix (`known_fix` on a returned error, `KnownFailureError` on a raised one); an unrecoverable one, or the same failure 3 times in a run, raises `UnrecoverableToolError`. Fingerprints are computed in the SDK with the same algorithm as the server (shared test vectors).
