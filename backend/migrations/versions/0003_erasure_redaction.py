"""Erasure also redacts the access log; tombstones are keyed (security review of D-042).

The access log stays append-only, with one exception: inside an erasure transaction
(integrity.erasure = on), a row's actor and/or target may be replaced by '[erased]', and nothing
else may change. So the audit trail keeps when, which role and which action, but no longer the
withdrawn participant's pseudonym or session ids. DELETE and TRUNCATE stay blocked.

The erasure tombstone column is renamed: it now holds an HMAC of the pseudonym under a key derived
from the field key, not a bare SHA-256 (8 base32 characters are about 2^40 values, which can be
searched exhaustively). Rows written before this migration hold the old SHA-256 (development data only).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = [
    "DROP TRIGGER access_log_append_only ON access_log",
    """
    CREATE TRIGGER access_log_no_delete BEFORE DELETE OR TRUNCATE ON access_log
        FOR EACH STATEMENT EXECUTE FUNCTION log_append_only()
    """,
    """
    CREATE FUNCTION access_log_redact_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF current_setting('integrity.erasure', true) = 'on'
           AND NEW.id = OLD.id AND NEW.at = OLD.at AND NEW.role = OLD.role AND NEW.action = OLD.action
           AND (NEW.actor = OLD.actor OR NEW.actor = '[erased]')
           AND (NEW.target = OLD.target OR NEW.target = '[erased]') THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'access_log is append-only: UPDATE blocked (only erasure may redact actor/target)';
    END $$
    """,
    """
    CREATE TRIGGER access_log_redact_only BEFORE UPDATE ON access_log
        FOR EACH ROW EXECUTE FUNCTION access_log_redact_only()
    """,
    "ALTER TABLE erasure_log RENAME COLUMN pseudonym_sha256 TO pseudonym_ref",
]

DOWNGRADE = [
    "ALTER TABLE erasure_log RENAME COLUMN pseudonym_ref TO pseudonym_sha256",
    "DROP TRIGGER access_log_redact_only ON access_log",
    "DROP FUNCTION access_log_redact_only()",
    "DROP TRIGGER access_log_no_delete ON access_log",
    """
    CREATE TRIGGER access_log_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON access_log
        FOR EACH STATEMENT EXECUTE FUNCTION log_append_only()
    """,
]


def upgrade() -> None:
    for sql in UPGRADE:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE:
        op.execute(sql)
