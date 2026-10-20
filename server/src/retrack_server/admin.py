"""Admin command for managing customers until the dashboard exists (Phase 12).

Runs with the admin database login (DATABASE_URL), never the server login.

    uv run retrack-admin create-project --org "Acme" --project support
    uv run retrack-admin create-key --project-id <uuid> --name ci
    uv run retrack-admin revoke-key --key-id <uuid>
    uv run retrack-admin set-trust --project-id <uuid> --tools orders_api,billing_api
    uv run retrack-admin review-list --project-id <uuid>
    uv run retrack-admin review-approve --item-id <uuid> --reviewer gokul --note "checked"
    uv run retrack-admin review-reject --item-id <uuid> --reviewer gokul --note "poisoned"
"""

import argparse
import os
import sys
from dataclasses import dataclass
from uuid import UUID

import psycopg

from retrack_server.api_keys import NewApiKey, create_api_key, revoke_api_key


@dataclass(frozen=True)
class CreatedProject:
    org_id: UUID
    project_id: UUID
    key: NewApiKey


def create_project(
    conn: psycopg.Connection, org_name: str, project_name: str, pepper: str
) -> CreatedProject:
    """Create a project (and its organization if new) with a first API key."""
    row = conn.execute(
        "select id from public.organizations where name = %s order by created_at limit 1",
        (org_name,),
    ).fetchone()
    org_id = (
        row[0]
        if row
        else conn.execute(
            "insert into public.organizations (name) values (%s) returning id", (org_name,)
        ).fetchone()[0]
    )
    project_id = conn.execute(
        "insert into public.projects (org_id, name) values (%s, %s) returning id",
        (org_id, project_name),
    ).fetchone()[0]
    key = create_api_key(conn, project_id, "default", pepper)
    return CreatedProject(org_id, project_id, key)


def set_trust(
    conn: psycopg.Connection, project_id: UUID, tools: list[str], task_trusted: bool
) -> None:
    """Set which tools a project trusts and whether its task text is trusted (docs/firewall.md)."""
    cleaned = sorted({tool.strip() for tool in tools if tool.strip()})
    conn.execute(
        "update public.projects set trusted_tools = %s, task_trusted = %s where id = %s",
        (cleaned, task_trusted, project_id),
    )


def list_reviews(conn: psycopg.Connection, project_id: UUID) -> list[dict]:
    """Open review items with what they concern and the firewall's findings."""
    rows = conn.execute(
        "select r.id, r.object_type, r.object_id, r.reason, r.created_at, p.title, p.status,"
        " coalesce((select string_agg(f.check_name || ': ' || f.detail, ' | ')"
        "   from public.firewall_findings f where f.object_id = r.object_id), '')"
        " from public.review_queue r left join public.playbooks p on p.id = r.object_id"
        " where r.project_id = %s and r.status = 'open' order by r.created_at",
        (project_id,),
    ).fetchall()
    keys = ("id", "object_type", "object_id", "reason", "created_at", "title", "status", "findings")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def resolve_review(
    conn: psycopg.Connection, item_id: UUID, *, approve: bool, reviewer: str, note: str
) -> None:
    """Approve (playbook becomes active, reviewer recorded) or reject (playbook retired)."""
    item = conn.execute(
        "select project_id, object_type, object_id, status from public.review_queue where id = %s",
        (item_id,),
    ).fetchone()
    if item is None or item[3] != "open":
        raise ValueError("review item not found or already resolved")
    project_id, object_type, object_id, _ = item
    conn.execute(
        "update public.review_queue set status = %s, reviewer = %s, resolution_note = %s,"
        " resolved_at = now() where id = %s",
        ("approved" if approve else "rejected", reviewer, note, item_id),
    )
    if object_type != "playbook":
        return
    if approve:
        conn.execute(
            "update public.playbooks set approved_by = %s, approved_at = now(), status = 'active'"
            " where id = %s",
            (reviewer, object_id),
        )
        conn.execute(
            "update public.provenance set reviewer_id = %s, approved_at = now()"
            " where project_id = %s and object_type = 'playbook' and object_id = %s",
            (reviewer, project_id, object_id),
        )
    else:
        conn.execute("update public.playbooks set status = 'retired' where id = %s", (object_id,))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retrack-admin")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("create-project", help="create a project and its first API key")
    p.add_argument("--org", required=True)
    p.add_argument("--project", required=True)
    k = commands.add_parser("create-key", help="add an API key to a project")
    k.add_argument("--project-id", required=True, type=UUID)
    k.add_argument("--name", default="default")
    r = commands.add_parser("revoke-key", help="revoke an API key")
    r.add_argument("--key-id", required=True, type=UUID)
    t = commands.add_parser("set-trust", help="set trusted tools and task trust for a project")
    t.add_argument("--project-id", required=True, type=UUID)
    t.add_argument("--tools", default="", help="comma-separated tool names; empty trusts none")
    t.add_argument("--task-trusted", action="store_true")
    rl = commands.add_parser("review-list", help="open review items for a project")
    rl.add_argument("--project-id", required=True, type=UUID)
    for name, text in (("review-approve", "approve"), ("review-reject", "reject")):
        rv = commands.add_parser(name, help=f"{text} a review item")
        rv.add_argument("--item-id", required=True, type=UUID)
        rv.add_argument("--reviewer", required=True)
        rv.add_argument("--note", default="")
    args = parser.parse_args(argv)

    url, pepper = os.environ.get("DATABASE_URL"), os.environ.get("RETRACK_KEY_PEPPER")
    if not url or not pepper:
        print("DATABASE_URL and RETRACK_KEY_PEPPER must be set", file=sys.stderr)
        return 2

    with psycopg.connect(url) as conn:
        if args.command == "create-project":
            created = create_project(conn, args.org, args.project, pepper)
            print(f"org_id:     {created.org_id}\nproject_id: {created.project_id}")
            print(f"api key:    {created.key.secret}   (shown once; store it now)")
        elif args.command == "create-key":
            key = create_api_key(conn, args.project_id, args.name, pepper)
            print(f"key_id:  {key.id}\napi key: {key.secret}   (shown once; store it now)")
        elif args.command == "review-list":
            for item in list_reviews(conn, args.project_id):
                print(
                    f"{item['id']}  {item['object_type']} {item['title']!r} [{item['status']}]"
                    f"\n    reason: {item['reason']}\n    findings: {item['findings']}"
                )
        elif args.command in ("review-approve", "review-reject"):
            resolve_review(
                conn,
                args.item_id,
                approve=args.command == "review-approve",
                reviewer=args.reviewer,
                note=args.note,
            )
            print("resolved")
        elif args.command == "set-trust":
            set_trust(conn, args.project_id, args.tools.split(","), args.task_trusted)
            print("trust settings updated")
        else:
            revoke_api_key(conn, args.key_id)
            print("revoked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
