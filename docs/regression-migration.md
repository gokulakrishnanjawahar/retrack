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

## Model migration
Triggered by `POST /v1/migrations` with a target model.
1. Replay all eval cases (or a sampled set) on the target model.
2. Produce a per-playbook report: still passes / needs re-learning / breaks.
3. Playbooks that pass are tagged with the new model in `validated_models`.
4. Failures produce a list of affected playbooks and failure cases for the developer to fix before switching.

Purpose: model providers deprecate models on fixed timelines, and newer models do not always behave the same on specific task types. Migration should become a checklist, not a scramble.

## Error fingerprinting and known-fix recovery
- Fingerprint = hash of (tool_name, error_class, normalised input shape).
- When a live failure matches a known fingerprint with a recovery playbook, the SDK can surface the recovery instead of blind retry.
- When a fingerprint is marked `unrecoverable`, the SDK's circuit-breaker stops retries early.
