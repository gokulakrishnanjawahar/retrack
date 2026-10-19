# Memory firewall

Persistent agent memory is an active attack surface. Research in 2026 (MemGhost, eTAMP, MemMorph, MemPoison, and an ICML 2026 systematic study) shows that a single injected record can steer future agent behaviour, that attacks transfer across memory backends (including Mem0), and that ordinary prompt-injection defences do not cover memory poisoning. Retrack treats the write path as hostile.

## Taint tracking
- Every step records `input_trust`: `trusted` (developer-defined prompts, internal tools marked trusted) or `untrusted` (email, web pages, user uploads, third-party tool output, anything not explicitly trusted).
- A run is tainted if any step consumed untrusted input that could influence later steps.
- Projects can mark specific tools as trusted in config (`projects.trusted_tools`, set with `retrack-admin set-trust`). Default for unknown tools: untrusted.
- The task text counts as untrusted input unless the project sets `projects.task_trusted` (for internal agents whose tasks come from staff). Decided 2026-10-18.
- **The server decides trust.** The SDK may send `input_trust`, but the worker recomputes it from the project's settings; client claims are ignored.
- Implemented rule (stricter than "could influence later steps"): a run is `trusted` only if its task is trusted and every step is trusted. A tool step is trusted if its tool is listed; an LLM step is trusted if the task and every earlier step are. A `quarantined` run is never downgraded.

## Rules
1. A tainted run cannot directly create or update an **active** playbook.
2. Tainted-run candidates go to `review_queue` unless they pass all automatic checks below; even then they start as `candidate`, not `active`.
3. Promotion to `active` requires either human approval or N independent trusted successes (`REQUIRED_TRUSTED_SUCCESSES`, default 3). Memory with quarantined sources needs a human. Implemented in `retrack_server.firewall.promotion_allowed` and enforced in the database by a trigger on `playbooks` (Phase 5).

## Automatic checks
- **Secret scanning:** regex and entropy checks for API keys, tokens, private keys, passwords; redact before storage and before embedding.
- **PII redaction:** emails, phone numbers, card numbers (Luhn-checked), Aadhaar (Verhoeff-checked), PAN, SSN.
- **Where (decided 2026-10-18):** both run at ingest, before anything is stored, on task text and tool arguments (`retrack_server.redaction`). Raw secrets and personal data are never stored. The SDK also strips well-known credentials before sending.
- **Injection classifier:** flags instructions embedded in data ("ignore previous", role changes, exfiltration URLs, requests to remember/store things). Uses an LLM (provider OPEN) plus heuristics.
- **Behavioural anomaly:** if a new or updated playbook would change which tools an agent selects for a task cluster versus its baseline, quarantine and flag.
- **Instruction-shaped memory:** playbook text must describe procedures for the task, not standing instructions about policy, permissions, recipients or URLs; flag any that do. Phase 5 uses a heuristic (URLs, override phrases, "always/never send...", credential words) that sends the playbook to review; the LLM classifier comes in Phase 8.

## Quarantine and provenance
- `status = quarantined` playbooks are never recalled.
- Every playbook version stores `content_hash` and a `provenance` record (source run IDs, input sources, trust level, reviewer).
- Any injected memory must be traceable to its source runs.

## Testing the firewall
Maintain an internal poisoning test suite (crafted runs with embedded instructions) and run it in CI. A change that lets any poisoning case reach `active` fails the build.
