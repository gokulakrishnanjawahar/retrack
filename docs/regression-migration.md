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

## Error fingerprinting and known-fix recovery
- Fingerprint = hash of (tool_name, error_class, normalised input shape).
- When a live failure matches a known fingerprint with a recovery playbook, the SDK can surface the recovery instead of blind retry.
- When a fingerprint is marked `unrecoverable`, the SDK's circuit-breaker stops retries early.
