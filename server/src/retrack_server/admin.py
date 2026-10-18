"""Admin command for managing customers until the dashboard exists (Phase 12).

Runs with the admin database login (DATABASE_URL), never the server login.

    uv run retrack-admin create-project --org "Acme" --project support
    uv run retrack-admin create-key --project-id <uuid> --name ci
    uv run retrack-admin revoke-key --key-id <uuid>
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
        else:
            revoke_api_key(conn, args.key_id)
            print("revoked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
