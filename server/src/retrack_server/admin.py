"""Admin command for managing customers (the dashboard covers the same tasks for users).

Runs with the admin database login (DATABASE_URL), never the server login.

    uv run retrack-admin create-project --org "Acme" --project support
    uv run retrack-admin create-key --project-id <uuid> --name ci
    uv run retrack-admin revoke-key --key-id <uuid>
    uv run retrack-admin set-trust --project-id <uuid> --tools orders_api,billing_api
    uv run retrack-admin review-list --project-id <uuid>
    uv run retrack-admin review-approve --item-id <uuid> --reviewer gokul --note "checked"
    uv run retrack-admin review-reject --item-id <uuid> --reviewer gokul --note "poisoned"
    uv run retrack-admin add-member --email you@example.com --project-id <uuid> --role owner
    uv run retrack-admin set-super-admin --email you@example.com
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


MEMBER_ROLES = ("owner", "admin", "member")


def _user_id(conn: psycopg.Connection, email: str) -> UUID:
    row = conn.execute(
        "select id from auth.users where lower(email) = lower(%s)", (email.strip(),)
    ).fetchone()
    if row is None:
        raise ValueError(f"no dashboard account for {email}: sign up first")
    return row[0]


def add_member(conn: psycopg.Connection, email: str, project_id: UUID, role: str) -> None:
    """Give an existing dashboard account a role in the organization that owns a project."""
    if role not in MEMBER_ROLES:
        raise ValueError(f"role must be one of {MEMBER_ROLES}")
    conn.execute(
        "insert into public.members (org_id, user_id, role)"
        " select org_id, %s, %s from public.projects where id = %s"
        " on conflict (org_id, user_id) do update set role = excluded.role",
        (_user_id(conn, email), role, project_id),
    )


def set_super_admin(conn: psycopg.Connection, email: str, value: bool) -> None:
    """Grant or remove cross-project analytics access (docs/decisions.md: Gokul only)."""
    user_id = _user_id(conn, email)
    if value:
        conn.execute(
            "insert into public.super_admins (user_id) values (%s) on conflict do nothing",
            (user_id,),
        )
    else:
        conn.execute("delete from public.super_admins where user_id = %s", (user_id,))


def set_unrecoverable(conn: psycopg.Connection, signature_id: UUID, value: bool | None) -> None:
    """Force a failure signature's unrecoverable flag, or None to return to the automatic
    rule (5+ occurrences and never recovered)."""
    conn.execute(
        "update public.failure_signatures set unrecoverable_override = %s,"
        " unrecoverable = coalesce(%s, occurrences >= 5 and recoveries = 0) where id = %s",
        (value, value, signature_id),
    )


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
    su = commands.add_parser("set-unrecoverable", help="override a failure's circuit breaker")
    su.add_argument("--signature-id", required=True, type=UUID)
    su.add_argument("--value", required=True, choices=["true", "false", "auto"])
    am = commands.add_parser("add-member", help="give an account a role in a project's org")
    am.add_argument("--email", required=True)
    am.add_argument("--project-id", required=True, type=UUID)
    am.add_argument("--role", default="owner", choices=MEMBER_ROLES)
    sa = commands.add_parser("set-super-admin", help="grant or remove cross-project analytics")
    sa.add_argument("--email", required=True)
    sa.add_argument("--remove", action="store_true")
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
        elif args.command == "set-unrecoverable":
            choice = {"true": True, "false": False, "auto": None}[args.value]
            set_unrecoverable(conn, args.signature_id, choice)
            print("updated")
        elif args.command == "add-member":
            add_member(conn, args.email, args.project_id, args.role)
            print("member added")
        elif args.command == "set-super-admin":
            set_super_admin(conn, args.email, not args.remove)
            print("super admin removed" if args.remove else "super admin granted")
        elif args.command == "set-trust":
            set_trust(conn, args.project_id, args.tools.split(","), args.task_trusted)
            print("trust settings updated")
        else:
            revoke_api_key(conn, args.key_id)
            print("revoked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
