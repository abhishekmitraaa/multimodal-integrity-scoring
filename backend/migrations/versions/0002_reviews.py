"""P4 reviewer workflow (D-039): review decisions and participant appeals.

Both tables are append-only, like events: a new decision supersedes an older one but never edits
it. Rows are removed only inside an erasure transaction (SPEC 10.7), through the same
integrity.erasure switch as events. Notes are encrypted at rest (SPEC 10.6), bound to their row.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE review_decisions (
        id            bigserial PRIMARY KEY,
        session_id    uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
        reviewer      text NOT NULL,
        decision      text NOT NULL CHECK (decision IN ('confirm', 'dismiss', 'inconclusive')),
        report_state  text NOT NULL,
        notes_ct      bytea NOT NULL,
        at            timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX review_decisions_session ON review_decisions (session_id, id)",
    """
    CREATE TABLE appeals (
        id          bigserial PRIMARY KEY,
        session_id  uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
        pseudonym   text NOT NULL REFERENCES participants (pseudonym) ON DELETE CASCADE,
        note_ct     bytea NOT NULL,
        at          timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX appeals_session ON appeals (session_id, id)",
    """
    CREATE TRIGGER review_decisions_append_only BEFORE UPDATE OR DELETE ON review_decisions
        FOR EACH ROW EXECUTE FUNCTION events_append_only()
    """,
    """
    CREATE TRIGGER review_decisions_no_truncate BEFORE TRUNCATE ON review_decisions
        FOR EACH STATEMENT EXECUTE FUNCTION events_append_only()
    """,
    """
    CREATE TRIGGER appeals_append_only BEFORE UPDATE OR DELETE ON appeals
        FOR EACH ROW EXECUTE FUNCTION events_append_only()
    """,
    """
    CREATE TRIGGER appeals_no_truncate BEFORE TRUNCATE ON appeals
        FOR EACH STATEMENT EXECUTE FUNCTION events_append_only()
    """,
]

DOWNGRADE = ["DROP TABLE appeals", "DROP TABLE review_decisions"]


def upgrade() -> None:
    for sql in UPGRADE:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE:
        op.execute(sql)
