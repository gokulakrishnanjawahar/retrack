"""Run the support-desk benchmark end to end through the real Retrack pipeline.

Flow: create a throwaway project -> learning round (agent without memory; Retrack
captures, scores via test signals, distils, auto-promotes) -> evaluation round (each new
task run twice with the same world seed: cold, and with recalled memory) -> report.
"""

import datetime as dt
import json
import os
import random
import re
import socket
import statistics
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg
import uvicorn

from benchmarks.support_desk.agents import ClaudeAgent, ScriptedAgent
from benchmarks.support_desk.world import TOOL_NAMES, TOOL_VERSIONS, Task, World
from retrack import Memory, Retrack
from retrack_server.admin import create_project, set_trust
from retrack_server.app import app, embedder_dependency, llm_dependency
from retrack_server.distiller import PLAYBOOK_SCHEMA
from retrack_server.embeddings import FakeEmbedder, VertexEmbedder
from retrack_server.llm import AnthropicLLM, LLMResponse
from retrack_server.worker import drain

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
INPUT_PRICE, OUTPUT_PRICE = 0.10, 0.50  # Claude Haiku 5.5, USD per 1M tokens (<100k prompts)


class ScriptedDistillLLM:
    """$0 distiller for fake mode: builds the playbook from the run record itself.

    Steps are the tools that succeeded, in order; pitfalls are the errors the run hit.
    """

    def generate_json(self, *, system: str, user: str, schema: dict, max_tokens: int):
        assert schema is PLAYBOOK_SCHEMA
        steps, pitfalls = [], []
        for line in user.splitlines():
            tool = re.search(r"\btool=(\w+)", line)
            if not tool:
                continue
            if "result=ok" in line and tool.group(1) not in [s["tool"] for s in steps]:
                steps.append({"action": f"Call {tool.group(1)}", "tool": tool.group(1)})
            returned = re.search(r'"error": "([^"]+)"', line)
            if returned and returned.group(1) not in pitfalls:
                pitfalls.append(returned.group(1))
        task = re.search(r"Task: (.*)", user)
        data = {
            "reusable": bool(steps),
            "title": (task.group(1) if task else "task")[:60],
            "task_pattern": re.sub(r"\d+", "N", task.group(1) if task else ""),
            "preconditions": "",
            "steps": steps,
            "pitfalls": "; ".join(pitfalls),
        }
        return LLMResponse(
            data=data, input_tokens=len(user) // 4, output_tokens=120, model="scripted"
        )


@dataclass
class Episode:
    phase: str
    condition: str  # "learn", "cold" or "memory"
    family: str
    success: bool
    tool_calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    playbooks_recalled: int
    warnings_recalled: int


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bootstrap_ci(values: list[float], seed: int, rounds: int = 2000) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(values) for _ in values) for _ in range(rounds))
    return means[int(rounds * 0.025)], means[int(rounds * 0.975)]


def run_benchmark(
    *,
    mode: str = "fake",
    learn: int = 16,
    evaluate: int = 20,
    seed: int = 7,
    learn_budget: int = 8,
    eval_budget: int = 4,
    keep: bool = False,
    approved_spend: bool = False,
    budget_usd: float = 0.10,
) -> dict[str, Any]:
    if mode not in ("fake", "real"):
        raise ValueError("mode must be 'fake' or 'real'")
    if mode == "real" and not approved_spend:
        raise SystemExit("real mode spends credits: pass --approved-spend once Gokul approves")

    pepper = os.environ["RETRACK_KEY_PEPPER"]
    if mode == "fake":
        agent_learn, agent_eval = ScriptedAgent(learn_budget), ScriptedAgent(eval_budget)
        distill_llm, embedder = ScriptedDistillLLM(), FakeEmbedder()
    else:
        key = os.environ["ANTHROPIC_API_KEY"]
        agent_learn, agent_eval = ClaudeAgent(learn_budget, key), ClaudeAgent(eval_budget, key)
        distill_llm = AnthropicLLM(api_key=key, model="claude-haiku-5-5", effort="low")
        embedder = VertexEmbedder(
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1"),
        )

    admin = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    created = create_project(admin, f"benchmark-{stamp}", "support-desk", pepper)
    project_id = created.project_id
    set_trust(admin, project_id, TOOL_NAMES, True)
    admin.execute("update public.projects set holdout_rate = 0 where id = %s", (project_id,))

    # The live worker (Supabase Cron -> Vercel) drains the same dev queue; pause it so it
    # cannot take benchmark jobs with production settings. Always re-enabled below.
    admin.execute(
        "select cron.alter_job(jobid, active := false) from cron.job"
        " where jobname = 'retrack-drain-runs'"
    )
    app.dependency_overrides[embedder_dependency] = lambda: embedder
    app.dependency_overrides[llm_dependency] = lambda: None
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    rt = Retrack(
        agent="support-desk",
        api_key=created.key.secret,
        base_url=f"http://127.0.0.1:{port}",
        model_id=agent_eval.model_id,
        tool_versions=TOOL_VERSIONS,
    )
    episodes: list[Episode] = []
    spent = 0.0

    def episode(task: Task, phase: str, condition: str, agent) -> None:
        nonlocal spent
        if mode == "real" and spent >= budget_usd:
            raise RuntimeError(f"stopped: spend ${spent:.4f} reached the ${budget_usd} cap")
        world = World(seed=seed)
        run_id = uuid.uuid4()
        memory = (
            rt.recall(task.text, run_id=run_id, timeout=5.0) if condition == "memory" else Memory()
        )
        usage = agent.run(
            world,
            task,
            memory.as_prompt(),
            {"callbacks": [rt.callback(task=task.text)], "run_id": run_id},
        )
        success = world.verify(task)
        rt.feedback(run_id, outcome="success" if success else "failure", source="test")
        cost = usage.tokens_in / 1e6 * INPUT_PRICE + usage.tokens_out / 1e6 * OUTPUT_PRICE
        spent += cost
        episodes.append(
            Episode(
                phase,
                condition,
                task.family,
                success,
                usage.tool_calls,
                usage.tokens_in,
                usage.tokens_out,
                cost,
                len(memory.playbooks),
                len(memory.warnings),
            )
        )

    def process() -> None:
        # From a laptop every send crosses the network to the database: allow time.
        if not rt.flush(timeout=900):
            raise RuntimeError("SDK could not deliver captured runs")
        print(f"  delivered {len(episodes)} runs; processing them", flush=True)
        with psycopg.connect(os.environ["SERVER_DATABASE_URL"], prepare_threshold=None) as conn:
            for _ in range(20):
                waiting = admin.execute(
                    "select count(*) from pgmq.q_runs where message->>'project_id' = %s",
                    (str(project_id),),
                ).fetchone()[0]
                if not waiting:
                    return
                drain(
                    conn,
                    llm=distill_llm,
                    embedder=embedder,
                    visibility_seconds=5,
                    time_budget_seconds=60,
                )
        raise RuntimeError("queue did not drain")

    try:
        print(f"learning round: {learn} tasks", flush=True)
        for task in World(seed=seed).tasks(learn):
            episode(task, "learn", "learn", agent_learn)
        process()
        print(f"evaluation round: {evaluate} tasks, each without and with memory", flush=True)
        for task in World(seed=seed).tasks(evaluate, offset=1):
            episode(task, "evaluate", "cold", agent_eval)
            episode(task, "evaluate", "memory", agent_eval)
        process()
        playbooks = [
            dict(
                zip(
                    ("title", "status", "support", "trusted_support", "uses", "successes"),
                    row,
                    strict=True,
                )
            )
            for row in admin.execute(
                "select title, status, support_count, trusted_support, uses, successes"
                " from public.playbooks where project_id = %s order by support_count desc",
                (project_id,),
            ).fetchall()
        ]
        signatures = admin.execute(
            "select count(*) from public.failure_signatures where project_id = %s", (project_id,)
        ).fetchone()[0]
    finally:
        admin.execute(
            "select cron.alter_job(jobid, active := true) from cron.job"
            " where jobname = 'retrack-drain-runs'"
        )
        rt.close(timeout=5)
        server.should_exit = True
        thread.join(timeout=5)
        app.dependency_overrides.clear()
        if not keep:
            for queue in ("q_runs", "q_runs_dlq"):
                admin.execute(
                    f"delete from pgmq.{queue} where message->>'project_id' = %s",
                    (str(project_id),),
                )
            admin.execute("delete from public.organizations where id = %s", (created.org_id,))
        admin.close()

    return _report(
        mode,
        seed,
        learn,
        evaluate,
        learn_budget,
        eval_budget,
        episodes,
        playbooks,
        signatures,
        spent,
        agent_eval.model_id,
    )


def _report(
    mode,
    seed,
    learn,
    evaluate,
    learn_budget,
    eval_budget,
    episodes,
    playbooks,
    signatures,
    spent,
    model_id,
) -> dict[str, Any]:
    def summary(rows: list[Episode]) -> dict[str, float]:
        return {
            "tasks": len(rows),
            "success_rate": statistics.fmean(e.success for e in rows),
            "tool_calls": statistics.fmean(e.tool_calls for e in rows),
            "tokens": statistics.fmean(e.tokens_in + e.tokens_out for e in rows),
            "cost_usd": statistics.fmean(e.cost_usd for e in rows),
        }

    cold = [e for e in episodes if e.condition == "cold"]
    warm = [e for e in episodes if e.condition == "memory"]
    success_diff = [float(w.success) - float(c.success) for c, w in zip(cold, warm, strict=True)]
    token_diff = [
        (w.tokens_in + w.tokens_out) - (c.tokens_in + c.tokens_out)
        for c, w in zip(cold, warm, strict=True)
    ]
    report = {
        "benchmark": "support-desk",
        "mode": mode,
        "agent_model": model_id,
        "date": dt.date.today().isoformat(),
        "settings": {
            "seed": seed,
            "learn_tasks": learn,
            "eval_tasks": evaluate,
            "learn_tool_budget": learn_budget,
            "eval_tool_budget": eval_budget,
        },
        "cold": summary(cold),
        "memory": summary(warm),
        "by_family": {
            family: {
                "cold": summary([e for e in cold if e.family == family]),
                "memory": summary([e for e in warm if e.family == family]),
            }
            for family in sorted({e.family for e in cold})
        },
        "success_rate_change": statistics.fmean(success_diff),
        "success_rate_change_95ci": _bootstrap_ci(success_diff, seed),
        "tokens_change_per_task": statistics.fmean(token_diff),
        "tokens_change_95ci": _bootstrap_ci(token_diff, seed),
        "memory_used_on_tasks": sum(e.playbooks_recalled > 0 for e in warm),
        "playbooks": playbooks,
        "failure_signatures": signatures,
        "spent_usd": round(spent, 6) if mode == "real" else 0.0,
        "episodes": [asdict(e) for e in episodes],
    }
    return report


def to_markdown(report: dict[str, Any]) -> str:
    c, m = report["cold"], report["memory"]
    lo, hi = report["success_rate_change_95ci"]
    tlo, thi = report["tokens_change_95ci"]
    lines = [
        f"# Support-desk benchmark ({report['mode']} mode, {report['date']})",
        "",
        f"Agent model: `{report['agent_model']}`. Settings: `{json.dumps(report['settings'])}`.",
        "",
        "| | Without memory | With Retrack memory |",
        "|---|---|---|",
        f"| Success rate | {c['success_rate']:.0%} | {m['success_rate']:.0%} |",
        f"| Tool calls per task | {c['tool_calls']:.2f} | {m['tool_calls']:.2f} |",
        f"| Tokens per task | {c['tokens']:.0f} | {m['tokens']:.0f} |",
        f"| Cost per task (USD) | {c['cost_usd']:.6f} | {m['cost_usd']:.6f} |",
        "",
        f"Success rate change: **{report['success_rate_change']:+.0%}** "
        f"(95% interval {lo:+.0%} to {hi:+.0%}).",
        f"Tokens per task change: **{report['tokens_change_per_task']:+.0f}** "
        f"(95% interval {tlo:+.0f} to {thi:+.0f}).",
        f"Memory was recalled on {report['memory_used_on_tasks']} of {m['tasks']} tasks.",
        "",
        "## By task family",
        "",
        "| Family | Success without | Success with | Tool calls without | Tool calls with |",
        "|---|---|---|---|---|",
    ]
    for family, data in report["by_family"].items():
        lines.append(
            f"| {family} | {data['cold']['success_rate']:.0%}"
            f" | {data['memory']['success_rate']:.0%}"
            f" | {data['cold']['tool_calls']:.2f} | {data['memory']['tool_calls']:.2f} |"
        )
    lines += [
        "",
        "## Memory learned",
        "",
        "| Playbook | Status | Support | Trusted | Uses | Successes |",
        "|---|---|---|---|---|---|",
    ]
    for p in report["playbooks"]:
        lines.append(
            f"| {p['title']} | {p['status']} | {p['support']} | {p['trusted_support']}"
            f" | {p['uses']} | {p['successes']} |"
        )
    lines += ["", f"Failure signatures recorded: {report['failure_signatures']}."]
    if report["mode"] == "fake":
        lines += [
            "",
            "> Fake mode uses a scripted agent and a $0 test embedder. It proves the pipeline",
            "> works end to end; its numbers are not evidence of real-world gains.",
        ]
    else:
        lines += ["", f"Spent: ${report['spent_usd']:.4f}."]
    return "\n".join(lines) + "\n"


def save(report: dict[str, Any]) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(exist_ok=True)
    base = RESULTS_DIR / f"support_desk_{report['mode']}_{report['date']}"
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, default=str))
    md_path.write_text(to_markdown(report))
    return json_path, md_path
