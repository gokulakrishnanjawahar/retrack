"""Taint tracking: the server decides trust from the project's settings, never the client."""

import uuid

from retrack_server.firewall import process_run


def set_trust(conn, project_id, tools, task_trusted):
    conn.execute(
        "update public.projects set trusted_tools = %s, task_trusted = %s where id = %s",
        (tools, task_trusted, project_id),
    )


def taint(conn, run_id):
    return conn.execute(
        "select taint_level, processed_at is not null from public.runs where id = %s", (run_id,)
    ).fetchone()


def step_trust(conn, run_id):
    rows = conn.execute(
        "select input_trust from public.steps where run_id = %s order by idx", (run_id,)
    ).fetchall()
    return [r[0] for r in rows]


def test_defaults_are_untrusted(conn, tenants):
    a, _ = tenants
    assert conn.execute(
        "select trusted_tools, task_trusted from public.projects where id = %s", (a.project_id,)
    ).fetchone() == ([], False)


def test_trusted_task_and_trusted_tools_make_a_trusted_run(conn, tenants):
    a, _ = tenants
    set_trust(conn, a.project_id, ["orders_api"], True)
    process_run(conn, a.project_id, a.run_id)
    assert taint(conn, a.run_id) == ("trusted", True)
    assert step_trust(conn, a.run_id) == ["trusted"]


def test_untrusted_tool_taints_the_run(conn, tenants):
    a, _ = tenants
    set_trust(conn, a.project_id, ["billing_api"], True)
    process_run(conn, a.project_id, a.run_id)
    assert taint(conn, a.run_id) == ("untrusted", True)
    assert step_trust(conn, a.run_id) == ["untrusted"]


def test_untrusted_task_taints_the_run(conn, tenants):
    a, _ = tenants
    set_trust(conn, a.project_id, ["orders_api"], False)
    process_run(conn, a.project_id, a.run_id)
    assert taint(conn, a.run_id)[0] == "untrusted"


def test_client_trust_claims_are_ignored(conn, tenants):
    a, _ = tenants
    conn.execute("update public.steps set input_trust = 'trusted' where run_id = %s", (a.run_id,))
    set_trust(conn, a.project_id, [], True)
    process_run(conn, a.project_id, a.run_id)
    assert step_trust(conn, a.run_id) == ["untrusted"]
    assert taint(conn, a.run_id)[0] == "untrusted"


def test_llm_only_run_follows_task_trust(conn, tenants):
    a, _ = tenants
    run_id = uuid.uuid4()
    conn.execute(
        "insert into public.runs (id, project_id, agent_id, task_text, model_id)"
        " values (%s, %s, %s, 'think', 'm')",
        (run_id, a.project_id, a.agent_id),
    )
    conn.execute(
        "insert into public.steps (project_id, run_id, idx, type) values (%s, %s, 0, 'llm')",
        (a.project_id, run_id),
    )
    set_trust(conn, a.project_id, [], True)
    process_run(conn, a.project_id, run_id)
    assert taint(conn, run_id)[0] == "trusted"


def test_quarantined_run_is_never_downgraded(conn, tenants):
    a, _ = tenants
    conn.execute("update public.runs set taint_level = 'quarantined' where id = %s", (a.run_id,))
    set_trust(conn, a.project_id, ["orders_api"], True)
    process_run(conn, a.project_id, a.run_id)
    assert taint(conn, a.run_id)[0] == "quarantined"


def test_another_projects_trust_list_is_never_used(conn, tenants):
    a, b = tenants
    set_trust(conn, b.project_id, ["orders_api"], True)
    process_run(conn, a.project_id, a.run_id)
    assert taint(conn, a.run_id)[0] == "untrusted"
