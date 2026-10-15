# Memory firewall

Persistent agent memory is an active attack surface. Research in 2026 (MemGhost, eTAMP, MemMorph, MemPoison, and an ICML 2026 systematic study) shows that a single injected record can steer future agent behaviour, that attacks transfer across memory backends (including Mem0), and that ordinary prompt-injection defences do not cover memory poisoning. Retrack treats the write path as hostile.

## Taint tracking
- Every step records `input_trust`: `trusted` (developer-defined prompts, internal tools marked trusted) or `untrusted` (email, web pages, user uploads, third-party tool output, anything not explicitly trusted).
- A run is tainted if any step consumed untrusted input that could influence later steps.
- Projects can mark specific tools as trusted in config. Default for unknown tools: untrusted.

## Rules
1. A tainted run cannot directly create or update an **active** playbook.
2. Tainted-run candidates go to `review_queue` unless they pass all automatic checks below; even then they start as `candidate`, not `active`.
3. Promotion to `active` requires either human approval or N independent trusted successes (configurable).

## Automatic checks
- **Secret scanning:** regex and entropy checks for API keys, tokens, private keys, passwords; redact before storage and before embedding.
- **PII redaction:** emails, phone numbers, card-like numbers, government IDs; redact before embedding.
- **Injection classifier:** flags instructions embedded in data ("ignore previous", role changes, exfiltration URLs, requests to remember/store things). Uses an LLM (provider OPEN) plus heuristics.
- **Behavioural anomaly:** if a new or updated playbook would change which tools an agent selects for a task cluster versus its baseline, quarantine and flag.
- **Instruction-shaped memory:** playbook text must describe procedures for the task, not standing instructions about policy, permissions, recipients or URLs; flag any that do.

## Quarantine and provenance
- `status = quarantined` playbooks are never recalled.
- Every playbook version stores `content_hash` and a `provenance` record (source run IDs, input sources, trust level, reviewer).
- Any injected memory must be traceable to its source runs.

## Testing the firewall
Maintain an internal poisoning test suite (crafted runs with embedded instructions) and run it in CI. A change that lets any poisoning case reach `active` fails the build.
