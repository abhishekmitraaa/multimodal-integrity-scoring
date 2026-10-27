"""Named staff accounts (D-044): one token per reviewer or admin, so decisions name a person.

Only a SHA-256 of each token is stored (tokens are 256-bit random, so a plain hash is enough).
Accounts are disabled, never deleted, so decisions and log entries keep a valid author.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE staff_accounts (
        handle        text PRIMARY KEY CHECK (handle ~ '^[a-z][a-z0-9-]{2,31}$'),
        role          text NOT NULL CHECK (role IN ('reviewer', 'admin')),
        token_sha256  bytea NOT NULL UNIQUE,
        created_at    timestamptz NOT NULL DEFAULT now(),
        disabled_at   timestamptz
    )
    """,
    """
    CREATE FUNCTION staff_accounts_no_delete() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'staff_accounts: accounts are disabled, never deleted (% blocked)', TG_OP;
    END $$
    """,
    """
    CREATE TRIGGER staff_accounts_no_delete BEFORE DELETE OR TRUNCATE ON staff_accounts
        FOR EACH STATEMENT EXECUTE FUNCTION staff_accounts_no_delete()
    """,
]

DOWNGRADE = [
    "DROP TABLE staff_accounts",
    "DROP FUNCTION staff_accounts_no_delete()",
]


def upgrade() -> None:
    for sql in UPGRADE:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE:
        op.execute(sql)
