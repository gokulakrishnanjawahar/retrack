"""GET /v1/metrics (docs/api.md, docs/recall-gating.md "Holdout"): memory's measured effect.

Runs that asked for memory are compared with holdout runs (which asked but got none), on
known outcomes only: success rate, tokens and cost per run. Holdout results need at least
MIN_HOLDOUT_EVIDENCE known outcomes before the lift should be trusted.
"""

from typing import Any
from uuid import UUID

import psycopg

from retrack_server.db import project_scope

MIN_HOLDOUT_EVIDENCE = 20

GROUPS_SQL = """
select r.holdout, count(*) as runs,
       count(*) filter (where r.outcome <> 'unknown') as known,
       count(*) filter (where r.outcome = 'success') as successes,
       avg(r.tokens_in + r.tokens_out)::float as avg_tokens,
       avg(r.cost_usd)::float as avg_cost
  from public.runs r
 where r.project_id = %(project)s and r.created_at > now() - make_interval(days => %(days)s)
   and exists (select 1 from public.recalls c where c.project_id = r.project_id and c.run_id = r.id)
 group by r.holdout
"""

OVERALL_SQL = """
select count(*), count(*) filter (where outcome <> 'unknown'),
       count(*) filter (where outcome = 'success')
  from public.runs
 where project_id = %(project)s and created_at > now() - make_interval(days => %(days)s)
"""

RECALLS_SQL = """
select count(*), count(*) filter (where holdout),
       count(*) filter (where not holdout and cardinality(playbook_ids) > 0),
       percentile_cont(0.5) within group (order by latency_ms),
       percentile_cont(0.95) within group (order by latency_ms)
  from public.recalls
 where project_id = %(project)s and created_at > now() - make_interval(days => %(days)s)
"""


def _rate(successes: int, known: int) -> float | None:
    return successes / known if known else None


def _change(treated: float | None, holdout: float | None) -> float | None:
    return treated / holdout - 1 if treated is not None and holdout else None


def project_metrics(conn: psycopg.Connection, project_id: UUID, days: int) -> dict[str, Any]:
    params = {"project": project_id, "days": days}
    with project_scope(conn, project_id):
        groups = {row[0]: row[1:] for row in conn.execute(GROUPS_SQL, params).fetchall()}
        runs, known, successes = conn.execute(OVERALL_SQL, params).fetchone()
        total, holdout_recalls, hits, p50, p95 = conn.execute(RECALLS_SQL, params).fetchone()

    def group(holdout: bool) -> dict[str, Any]:
        n, k, s, tokens, cost = groups.get(holdout, (0, 0, 0, None, None))
        return {
            "runs": n,
            "known": k,
            "successes": s,
            "success_rate": _rate(s, k),
            "avg_tokens": tokens,
            "avg_cost_usd": cost,
        }

    memory, holdout = group(False), group(True)
    lift = (
        (memory["success_rate"] - holdout["success_rate"]) * 100
        if memory["success_rate"] is not None and holdout["success_rate"] is not None
        else None
    )
    served = total - holdout_recalls
    return {
        "days": days,
        "runs": runs,
        "success_rate": _rate(successes, known),
        "memory": memory,
        "holdout": holdout,
        "lift_points": lift,
        "token_change": _change(memory["avg_tokens"], holdout["avg_tokens"]),
        "cost_change": _change(memory["avg_cost_usd"], holdout["avg_cost_usd"]),
        "enough_evidence": holdout["known"] >= MIN_HOLDOUT_EVIDENCE and memory["known"] > 0,
        "recalls": {
            "total": total,
            "holdout": holdout_recalls,
            "hit_rate": hits / served if served else None,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
        },
    }
