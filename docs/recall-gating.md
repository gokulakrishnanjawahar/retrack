# Recall gating and plan replay

Wrong memory is worse than no memory. A playbook is injected only when it clearly applies.

## Retrieval
1. Filter by project, agent, and `status = active`.
2. Hybrid search: vector similarity on task embedding + full-text match, merged (e.g. reciprocal rank fusion).
3. Take top candidates (e.g. 20), compute gate score, keep those above threshold, return at most `max_playbooks`.
4. Also return failure signatures whose fingerprint matches the task context or known tools.

## Gate score
```
score = similarity × confidence × success_rate × freshness × version_match
```
- **similarity:** cosine similarity of task embeddings (0 to 1).
- **confidence:** confidence of the outcomes that produced the playbook.
- **success_rate:** share of successful uses after recall.
- **freshness:** decays with time since last successful use (exponential, tunable half-life).
- **version_match:** 1.0 if validated on current model and tool versions; 0.6 if only tool versions match; 0 if any used tool has a breaking version change.

Default threshold: **0.72** per agent, tuned later from holdout data. Thresholds live in config, not code.

## Plan replay (skip planning)
Allowed only when all hold:
- similarity ≥ 0.95
- success_rate ≥ 0.9 over ≥ 20 uses
- exact model and tool version match

The agent still validates the result. Any failure on replay demotes the playbook (status back to candidate or quarantined).

*As built (Phase 11):* recall sets `replay_eligible` per playbook and a top-level `replay_plan` (`playbook_id`, `version`, `steps`) when the top playbook qualifies: hybrid mode, similarity >= 0.95, at least 20 uses with at least 90% real success (not the prior), the request's `model_id` in `validated_models`, and every tool version exactly equal. Runs that follow it report `replay_of` (SDK: `rt.callback(replay_of=...)`); a failed replay sets an active playbook back to `candidate` and opens a review item.

## Learning loop
- Record which playbooks were recalled on each run (`runs.recalled_playbook_ids`).
- After scoring, update each recalled playbook's `uses` and `success_rate`.
- Auto-retire playbooks whose success rate falls below a floor after enough uses.

**Content changes and replay:** an approved fleet update or a rollback replaces a playbook's steps and clears its `validated_models`, so plan replay stays off until the new content is validated on the model again (`retrack migrate`).

## Holdout
A configurable slice of runs (default 10%) gets no memory. Metrics compare holdout vs treated runs on success rate, tokens and cost.

## Failure behaviour
Recall has a strict timeout (see `constraints.md`). On timeout or error, the SDK returns empty memory and the agent proceeds. Never block the agent.

## Defaults decided 2026-10-20
- **New playbooks:** success rate counts the supporting source runs as prior successes: `(successes + support) / (uses + support)`, so a new playbook starts at 1.0 and adjusts with use.
- **Breaking tool change:** a different major version (leading number: `v3` vs `v4`, `2026-…` vs `2027-…`). Requests that omit `model_id` or `tool_versions` are not penalised for them.
- **Freshness:** half-life 30 days from the last success.
- **Auto-retire:** success below 50% after 10 or more uses.
- **Holdout:** 10% per project (`projects.holdout_rate`), decided deterministically from project and run id.
- **Threshold:** `agents.recall_threshold`, default 0.72.
- **Embedding at recall:** 150 ms budget; slower or disabled embeddings fall back to keyword-only search.
- **Latency check:** candidate search over 10,000 active playbooks measured at about 52 ms server execution after fixing the query plan (target p50 under 120 ms).
