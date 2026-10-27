"""Study protocol (D-046, SPEC 12.2): browser covariates, condition assignments and labels.

- sessions: browser brand/version and cross-origin isolation, logged for every session (covariates;
  for study participants also enforced: allowed browser, same brand in both sittings, isolated).
- participants.study_protocol: every real participant; dev testers may opt in.
- study_assignments: the participant's sitting-2 plan (slot -> task, condition), Latin square.
- study_labels: each study session's condition and the attack onset the participant marks. Kept
  apart from events: the scoring path and the reviewer views never read it (reviewers stay blind).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

CONDITIONS = "('genuine', 'A1', 'A2', 'A3a', 'A3b', 'A4', 'A5', 'A7', 'A8')"

UPGRADE = [
    "ALTER TABLE sessions ADD COLUMN browser_brand text, ADD COLUMN browser_version text, ADD COLUMN cross_origin_isolated boolean",
    "ALTER TABLE participants ADD COLUMN study_protocol boolean NOT NULL DEFAULT false",
    f"""
    CREATE TABLE study_assignments (
        pseudonym   text NOT NULL REFERENCES participants (pseudonym) ON DELETE CASCADE,
        slot        integer NOT NULL CHECK (slot >= 0),
        problem_id  text NOT NULL,
        condition   text NOT NULL CHECK (condition IN {CONDITIONS}),
        PRIMARY KEY (pseudonym, slot)
    )
    """,
    f"""
    CREATE TABLE study_labels (
        session_id       uuid PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
        condition        text NOT NULL CHECK (condition IN {CONDITIONS}),
        scripted         boolean NOT NULL DEFAULT false,
        onset_client_us  bigint,
        onset_at         timestamptz
    )
    """,
]

DOWNGRADE = [
    "DROP TABLE study_labels",
    "DROP TABLE study_assignments",
    "ALTER TABLE participants DROP COLUMN study_protocol",
    "ALTER TABLE sessions DROP COLUMN browser_brand, DROP COLUMN browser_version, DROP COLUMN cross_origin_isolated",
]


def upgrade() -> None:
    for sql in UPGRADE:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE:
        op.execute(sql)
