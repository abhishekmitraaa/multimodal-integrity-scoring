"""Named staff accounts (D-044): one token per reviewer or admin, so decisions name a person.

The token is printed once, at creation; only its hash is stored. Give it to the person over a
private channel, never by email in plain text. Accounts are disabled, never deleted.

Usage:
  python scripts/staff_accounts.py add dr-rao --role reviewer
  python scripts/staff_accounts.py list
  python scripts/staff_accounts.py disable dr-rao
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

from integrity_backend.crypto import FieldCipher
from integrity_backend.settings import load_settings
from integrity_backend.store import Store


async def run(args: argparse.Namespace) -> Any:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        store = Store(engine, FieldCipher(settings.data_key), {})
        if args.action == "add":
            token = await store.create_staff_account(args.handle, args.role)
            await store.log_access("admin-cli", "admin", f"create_staff_account:{args.role}", args.handle)
            return token
        if args.action == "disable":
            done = await store.disable_staff_account(args.handle)
            if done:
                await store.log_access("admin-cli", "admin", "disable_staff_account", args.handle)
            return done
        return await store.list_staff_accounts()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Named staff accounts (D-044).")
    parser.add_argument("action", choices=["add", "list", "disable"])
    parser.add_argument("handle", nargs="?", help="lower-case letters, digits and hyphens, 3-32 characters")
    parser.add_argument("--role", choices=["reviewer", "admin"], default="reviewer")
    args = parser.parse_args(argv)
    if args.action != "list" and not args.handle:
        parser.error("a handle is needed")
    try:
        result = asyncio.run(run(args))
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - database constraint messages are the useful part
        print(f"failed: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 1
    if args.action == "add":
        print(f"created {args.role} '{args.handle}'. Token (shown once; give it to them privately):\n{result}")
    elif args.action == "disable":
        print(f"disabled '{args.handle}'" if result else f"no enabled account '{args.handle}'")
        return 0 if result else 1
    else:
        for a in result:
            print(f"{a['handle']:<32} {a['role']:<9} created {a['created_at'][:10]}"
                  + (f"  DISABLED {a['disabled_at'][:10]}" if a["disabled_at"] else ""))
        if not result:
            print("no named accounts yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
