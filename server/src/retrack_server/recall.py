"""Recall (docs/recall-gating.md): the right playbooks and warnings before a task.

Wrong memory is worse than no memory, so a playbook is returned only when its gate score

    similarity x confidence x success_rate x freshness x version_match

reaches the agent's threshold (default 0.72). Candidates come from hybrid search over
ACTIVE playbooks: the 20 nearest by meaning plus the 20 best by keywords. If embeddings
are off or slow, recall falls back to keywords only; it never blocks the agent.
"""

import concurrent.futures
import datetime as dt
import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import psycopg

from retrack_server.db import increment_usage, pipeline_scope, project_scope
from retrack_server.embeddings import Embedder, to_vector_literal
from retrack_server.redaction import redact_text
from retrack_server.schemas import RecallIn

FRESHNESS_HALF_LIFE_DAYS = 30
EMBED_TIMEOUT_SECONDS = 0.15
CANDIDATES_PER_METHOD = 20
WARNING_MIN_OCCURRENCES = 2
MAX_WARNINGS = 5
RETIRE_AFTER_USES = 10
RETIRE_BELOW_SUCCESS = 0.5

_embed_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="embed")

# Hybrid candidate search. Run inside project_scope (RLS: active playbooks of the project).
CANDIDATES_SQL = """
with vec as (
  select id, row_number() over () as rank from (
    select id from public.playbooks
    where project_id = %(project_id)s and agent_id = %(agent_id)s and status = 'active'
      and embedding_model = %(model)s
    order by embedding operator(extensions.<=>) %(vector)s::extensions.halfvec
    limit 20
  ) nearest
),
fts as (
  select id, row_number() over (order by score desc) as rank from (
    select id, ts_rank_cd(search_text, to_tsquery('english', %(query)s)) as score
    from public.playbooks
    where project_id = %(project_id)s and agent_id = %(agent_id)s and status = 'active'
      and search_text @@ to_tsquery('english', %(query)s)
    order by score desc
    limit 20
  ) best
),
candidates as (
  select coalesce(vec.id, fts.id) as id,
         coalesce(1.0 / (60 + vec.rank), 0) + coalesce(1.0 / (60 + fts.rank), 0) as rrf
  from vec full join fts on fts.id = vec.id
)
select p.id, p.version, p.title, p.preconditions, p.steps, p.pitfalls, p.confidence,
       p.successes, p.uses, p.support_count, p.last_success_at, p.validated_models,
       p.tool_versions,
       1 - (p.embedding operator(extensions.<=>) %(vector)s::extensions.halfvec) as similarity,
       c.rrf
from candidates c
join public.playbooks p on p.id = c.id
-- An explicit id list gives the planner a direct primary-key lookup for the details.
where p.id = any(array(select id from candidates))
"""

KEYWORD_SQL = """
select p.id, p.version, p.title, p.preconditions, p.steps, p.pitfalls, p.confidence,
       p.successes, p.uses, p.support_count, p.last_success_at, p.validated_models,
       p.tool_versions,
       ts_rank_cd(p.search_text, to_tsquery('english', %(query)s), 32) as similarity,
       0.0 as rrf
from public.playbooks p
where p.project_id = %(project_id)s and p.agent_id = %(agent_id)s and p.status = 'active'
  and p.search_text @@ to_tsquery('english', %(query)s)
order by similarity desc
limit 20
"""


@dataclass
class RecallResult:
    recall_id: str | None = None
    playbooks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    holdout: bool = False
    mode: str = "hybrid"


# Gate building blocks ----------------------------------------------------------------


def major_version(version: str) -> str | None:
    """The leading number of a version string: 'v3.2' -> '3', '2026-09' -> '2026'."""
    match = re.search(r"\d+", version or "")
    return match.group(0) if match else None


def version_match(
    validated_models: list[str],
    playbook_tools: dict[str, str],
    model_id: str | None,
    tool_versions: dict[str, str],
) -> float:
    """1.0 if model and tools match, 0.6 if only tools match, 0.0 on a breaking tool change.

    A different major version of a tool the playbook uses is breaking. A request that does
    not name its model or tools is not penalised for them.
    """
    for tool, version in (playbook_tools or {}).items():
        if tool in tool_versions and major_version(tool_versions[tool]) != major_version(version):
            return 0.0
    if model_id is None or model_id in (validated_models or []):
        return 1.0
    return 0.6


def freshness(last_success_at: dt.datetime | None, now: dt.datetime) -> float:
    if last_success_at is None:
        return 1.0
    days = max((now - last_success_at).total_seconds() / 86400, 0.0)
    return 0.5 ** (days / FRESHNESS_HALF_LIFE_DAYS)


def prior_success_rate(successes: int, uses: int, support: int) -> float:
    """Success after recall, with the supporting source runs counted as prior successes."""
    total = uses + support
    return (successes + support) / total if total else 1.0


def gate_score(similarity, confidence, success_rate, fresh, versions) -> float:
    return similarity * confidence * success_rate * fresh * versions


def in_holdout(project_id: UUID, run_id: UUID, rate: float) -> bool:
    """Deterministic per run, so retries of the same run get the same answer."""
    digest = hashlib.sha256(f"{project_id}:{run_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


# Recall --------------------------------------------------------------------------------


def _keyword_query(text: str) -> str | None:
    words = sorted(set(re.findall(r"[a-z]{3,}", text.lower())))[:30]
    return " | ".join(words) or None


def _embed_with_timeout(embedder: Embedder | None, text: str) -> str | None:
    if embedder is None:
        return None
    future = _embed_pool.submit(embedder.embed, [text])
    try:
        return to_vector_literal(future.result(timeout=EMBED_TIMEOUT_SECONDS)[0])
    except Exception:  # timeout or provider error: fall back to keywords
        return None


def _warnings(conn, project_id, agent_id, tool_versions) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select f.id, f.fingerprint, f.tool_name, f.error_class, f.input_shape, f.occurrences,"
        " f.last_seen, f.unrecoverable, p.title"
        " from public.failure_signatures f"
        " left join public.playbooks p on p.id = f.recovery_playbook_id"
        " where f.project_id = %s and f.agent_id = %s and f.occurrences >= %s"
        " and (cardinality(%s::text[]) = 0 or f.tool_name = any(%s::text[]))"
        " order by f.occurrences desc, f.last_seen desc limit %s",
        (
            project_id,
            agent_id,
            WARNING_MIN_OCCURRENCES,
            list(tool_versions),
            list(tool_versions),
            MAX_WARNINGS,
        ),
    ).fetchall()
    warnings = []
    for sig_id, fp, tool, error, shape, count, last_seen, unrecoverable, recovery in rows:
        message = (
            f"{tool} has failed with {error} {count} times (arguments: {shape or 'none'}); "
            + ("it cannot be recovered by retrying" if unrecoverable else "plan for this")
        )
        warnings.append(
            {
                "id": str(sig_id),
                "fingerprint": fp,
                "tool": tool,
                "error_class": error,
                "occurrences": count,
                "last_seen": last_seen.isoformat(),
                "message": message,
                "recovery": recovery,
            }
        )
    return warnings


def recall(
    conn: psycopg.Connection,
    project_id: UUID,
    request: RecallIn,
    embedder: Embedder | None,
    now: dt.datetime | None = None,
) -> RecallResult:
    started = time.monotonic()
    now = now or dt.datetime.now(dt.UTC)
    task, _ = redact_text(request.task)
    run_key = request.run_id or uuid.uuid4()
    tools = request.tool_versions

    with project_scope(conn, project_id):
        project = conn.execute(
            "select holdout_rate from public.projects where id = %s", (project_id,)
        ).fetchone()
        agent = conn.execute(
            "select id, recall_threshold from public.agents where project_id = %s and name = %s",
            (project_id, request.agent),
        ).fetchone()
        increment_usage(conn, recalls_served=1)
        if agent is None:
            return RecallResult(mode="no_agent")
        agent_id, threshold = agent

        if in_holdout(project_id, run_key, project[0]):
            result = RecallResult(holdout=True, mode="holdout")
        else:
            # Embedding happens with the transaction open but bounded by a short timeout.
            vector = _embed_with_timeout(embedder, task)
            query = _keyword_query(task)
            rows = []
            if vector is not None:
                conn.execute("set local hnsw.iterative_scan = relaxed_order")
                rows = conn.execute(
                    CANDIDATES_SQL,
                    {
                        "project_id": project_id,
                        "agent_id": agent_id,
                        "model": embedder.model,
                        "vector": vector,
                        "query": query or "''",
                    },
                ).fetchall()
            elif query is not None:
                rows = conn.execute(
                    KEYWORD_SQL,
                    {"project_id": project_id, "agent_id": agent_id, "query": query},
                ).fetchall()
            scored = []
            for (
                pb_id,
                version,
                title,
                pre,
                steps,
                pitfalls,
                confidence,
                successes,
                uses,
                support,
                last_success,
                models,
                pb_tools,
                similarity,
                rrf,
            ) in rows:
                score = gate_score(
                    max(float(similarity or 0.0), 0.0),
                    confidence,
                    prior_success_rate(successes, uses, support),
                    freshness(last_success, now),
                    version_match(models, pb_tools, request.model_id, tools),
                )
                if score >= threshold:
                    scored.append((score, rrf, pb_id, version, title, pre, steps, pitfalls))
            scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
            result = RecallResult(
                mode="hybrid" if vector is not None else "keyword",
                playbooks=[
                    {
                        "id": str(pb_id),
                        "version": version,
                        "score": round(score, 4),
                        "title": title,
                        "preconditions": pre,
                        "steps": steps,
                        "pitfalls": pitfalls,
                    }
                    for score, _rrf, pb_id, version, title, pre, steps, pitfalls in scored[
                        : request.max_playbooks
                    ]
                ],
                warnings=_warnings(conn, project_id, agent_id, tools),
            )

        result.recall_id = str(
            conn.execute(
                "insert into public.recalls (project_id, agent_id, run_id, playbook_ids,"
                " warning_ids, holdout, mode, latency_ms)"
                " values (%s, %s, %s, %s::uuid[], %s::uuid[], %s, %s, %s) returning id",
                (
                    project_id,
                    agent_id,
                    request.run_id,
                    [p["id"] for p in result.playbooks],
                    [w["id"] for w in result.warnings],
                    result.holdout,
                    result.mode,
                    int((time.monotonic() - started) * 1000),
                ),
            ).fetchone()[0]
        )
    return result


# Learning loop -------------------------------------------------------------------------


def apply_learning(conn: psycopg.Connection, project_id: UUID, run_id: UUID) -> None:
    """Count a recalled run's outcome towards its playbooks, exactly once per outcome."""
    with pipeline_scope(conn, project_id):
        row = conn.execute(
            "select recalled_playbook_ids, outcome, recall_counted_as from public.runs"
            " where project_id = %s and id = %s",
            (project_id, run_id),
        ).fetchone()
        if row is None:
            raise LookupError(f"run {run_id} not found in project {project_id}")
        playbook_ids, outcome, counted = row
        if not playbook_ids or outcome not in ("success", "failure") or counted == outcome:
            return
        new_use = 1 if counted is None else 0
        success_delta = int(outcome == "success") - int(counted == "success")
        conn.execute(
            "update public.playbooks set"
            " uses = uses + %(use)s,"
            " successes = successes + %(delta)s,"
            " success_rate = (successes + %(delta)s + support_count)::real"
            "   / greatest(uses + %(use)s + support_count, 1),"
            " status = case"
            "   when status in ('active', 'candidate') and uses + %(use)s >= %(retire_uses)s"
            "     and (successes + %(delta)s)::real / (uses + %(use)s) < %(retire_rate)s"
            "   then 'retired' else status end"
            " where project_id = %(project_id)s and id = any(%(ids)s::uuid[])",
            {
                "use": new_use,
                "delta": success_delta,
                "retire_uses": RETIRE_AFTER_USES,
                "retire_rate": RETIRE_BELOW_SUCCESS,
                "project_id": project_id,
                "ids": playbook_ids,
            },
        )
        conn.execute(
            "update public.runs set recall_counted_as = %s where project_id = %s and id = %s",
            (outcome, project_id, run_id),
        )
