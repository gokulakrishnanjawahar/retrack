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
3. Promotion to `active` requires either human approval or N independent trusted successes (`REQUIRED_TRUSTED_SUCCESSES`, default 3). A trusted success counts only at hard-signal strength, confidence >= 0.8 (tests, business events, user feedback; decided 2026-10-20); AI-judge verdicts add support but never promote. Promotion is automatic: the distiller promotes a candidate as soon as the rule holds and no review item is open. Memory with quarantined sources needs a human. Implemented in `retrack_server.firewall.promotion_allowed` and enforced in the database by a trigger on `playbooks` (Phase 5).

## Automatic checks
- **Secret scanning:** regex and entropy checks for API keys, tokens, private keys, passwords; redact before storage and before embedding.
- **PII redaction:** emails, phone numbers, card numbers (Luhn-checked), Aadhaar (Verhoeff-checked), PAN, SSN.
- **Where (decided 2026-10-18):** both run at ingest, before anything is stored, on task text and tool arguments (`retrack_server.redaction`). Raw secrets and personal data are never stored. The SDK also strips well-known credentials before sending.
- **Injection classifier:** flags instructions embedded in data ("ignore previous", role changes, exfiltration URLs, requests to remember/store things). Uses an LLM (provider OPEN) plus heuristics.
- **Behavioural anomaly:** if a new or updated playbook would change which tools an agent selects for a task cluster versus its baseline, quarantine and flag.
- **Instruction-shaped memory:** playbook text must describe procedures for the task, not standing instructions about policy, permissions, recipients or URLs; flag any that do. Phase 5 uses a heuristic (URLs, override phrases, "always/never send...", credential words) that sends the playbook to review; the LLM classifier comes in Phase 8.

## How the checks run (Phase 8)
- **Every run (free):** heuristic scan (`retrack_server.injection`) of the run's *untrusted* content: untrusted task text, untrusted steps' arguments and results, and the final answer of an untrusted run. Patterns: override phrases, fake system roles and chat templates, persona switches, standing orders and "remember for the future", exfiltration links and tracking images, base64-hidden instructions, invisible Unicode (zero-width, bidirectional overrides, tag characters). A hit quarantines the run (`taint_level = quarantined`) and records a finding. Quarantined runs are never distilled.
- **Memory write path only (Claude Haiku 5.5):** when a new playbook is created from an untrusted run, the run record and the proposed playbook go through the LLM classifier (`retrack_server.classifier`); when an untrusted run would add support to an existing playbook, the run record is classified. The playbook text is also scanned with the heuristics and the instruction-shape check.
- **Anomaly:** a new playbook that uses a tool which similar playbooks of the agent (cosine >= 0.75) never use is quarantined.
- **Outcomes:** any blocking finding -> playbook `quarantined` + review item; instruction-shaped text -> review item; all clean -> `passed_automatic_checks = true`, which lets trusted support promote it (rule 2). Failure-signature tool and error names must be plain identifiers (they are shown to agents in warnings).
- **Findings** are stored in `firewall_findings` (check, severity, detail). Review with `retrack-admin review-list / review-approve / review-reject`.
- **Poisoning suite** (`server/tests/db/test_poisoning.py`): 20 attacks x 4 placements, plus a compromised distiller, under a fooled classifier; plus benign look-alikes that must still become active memory. Trusted follow-up runs (which would promote a poisoned playbook) are added whenever the poisoned run produced a playbook. About 20 minutes from a laptop because every job crosses the network to the database.

## Quarantine and provenance
- `status = quarantined` playbooks are never recalled.
- Every playbook version stores `content_hash` and a `provenance` record (source run IDs, input sources, trust level, reviewer).
- Any injected memory must be traceable to its source runs.

## Testing the firewall
Maintain an internal poisoning test suite (crafted runs with embedded instructions). A change that lets any poisoning case reach `active` fails the build. CI is deferred (see `decisions.md`): the suite runs in the full local test suite before each phase is committed.
