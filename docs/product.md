# Product

## Tagline
**Retrack builds experience for AI agents.**

## One line
Retrack is the learning layer for production AI agents: every run makes agents safer, cheaper and more reliable.

## What it does
1. **Capture** every agent run (task, plan, tool calls, results, tokens, model, tool versions).
2. **Verify** whether the run succeeded, using the strongest signal available.
3. **Distil** verified successes into playbooks and failures into failure signatures.
4. **Recall** the right playbooks and warnings before the agent's next similar task, only when confidence is high.
5. **Protect** memory with a firewall so poisoned or untrusted runs never become memory.
6. **Test** by turning every playbook and failure into a regression test.
7. **Migrate** safely by replaying memory against a new model before a forced model switch.
8. **Prove** value with a holdout group, so improvement is measured, not estimated.

## Problems it solves (2026 evidence)
| Pain | Retrack answer |
|---|---|
| Agents re-solve recurring tasks from scratch, wasting tokens and behaving inconsistently | Playbook recall and plan replay |
| Agents retry the same failing action in loops; costs become unpredictable | Failure signatures, known-fix recovery, circuit-breaker |
| Production failures recur because they never become tests | Memory store doubles as regression suite |
| Model providers deprecate models on fixed windows (e.g. Anthropic's 60-day deprecation-to-retirement); behaviour changes between versions | Model-migration replay report per playbook |
| Persistent memory is an attack surface (e.g. MemGhost poisoned agent memory via one email and transferred to Mem0; eTAMP targets trajectory memory) | Memory firewall: taint, quarantine, provenance |

## Positioning
Supermemory and Mem0 remember **what is true about users**. Retrack remembers **what worked and what failed for agents**, proves the savings, and keeps that memory safe.

## Ideal customer profile
- **Company:** seed to Series B software company, 5 to 50 engineers; agents are part of the product or core operations.
- **Workload:** repetitive agent tasks at volume (support resolution, data/ops pipelines, coding and code-review agents, back-office automation), roughly 10k+ runs per month.
- **Stack:** LangGraph or LangChain in Python; meaningful monthly model-API spend.
- **User (champion):** AI/agent engineer who owns reliability and token spend.
- **Buyer:** CTO, head of AI, or engineering manager.
- **Trigger events:** token bill spike; model deprecation notice; repeated production failure; security review asking how agent memory is protected.
- **Secondary:** AI agencies building agents for several clients (per-client playbooks); indie developers (adoption only).
- **Not a fit:** chatbots whose main need is user-fact memory; one-off non-repetitive tasks.

## Competitors and the gap
| Product | What it does | Gap Retrack targets |
|---|---|---|
| Supermemory | Hosted memory API for user and document memory | Facts, not verified agent procedures; no regression/migration |
| Mem0 | Managed memory API; publishes procedural-memory guidance | Shown vulnerable to MemGhost; no CI regression or holdout ROI |
| LangMem | LangChain's OSS SDK with episodic/procedural memory | Library only; no hosted governance, review, or ROI proof |
| ReMe (Alibaba) | TaskMemory from successful/failed tasks | Tied to Alibaba Cloud services |
| Braintrust, LangSmith | Evals, tracing, failed traces to regression datasets | Tests don't feed learning back to the agent at runtime |
| Brooder (OSS) | Snapshot testing across model upgrades | No memory |

Defensibility is the **combination**: verified learning + firewall + regression + migration in one store, plus measured ROI. Main threat: LangChain turning LangMem into a hosted product. Stay framework-flexible (OpenTelemetry ingestion later).

## Business notes for engineering
- Plans are Free, Pro and Team (no Enterprise for now); prices and limits are not decided, and plans are out of scope for the codebase. See `decisions.md`.
- Record usage (runs captured, recalls served) per project per day so billing can be added later.
- Open vs closed source is undecided; keep `sdk/` cleanly separable from `server/`.
