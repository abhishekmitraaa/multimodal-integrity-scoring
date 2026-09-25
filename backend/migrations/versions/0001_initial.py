"""P1 schema: participants, consent, sessions, append-only events, access and erasure logs.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# asyncpg prepares every statement, so each list item must be exactly one SQL statement.
UPGRADE = [
    """
    CREATE TABLE participants (
        pseudonym            text PRIMARY KEY,
        kind                 text NOT NULL CHECK (kind IN ('real', 'synthetic', 'dev')),
        token_sha256         bytea NOT NULL UNIQUE,
        created_at           timestamptz NOT NULL DEFAULT now(),
        withdrawn_at         timestamptz,
        modality_exclusions  jsonb NOT NULL DEFAULT '[]'::jsonb
    )
    """,
    """
    CREATE TABLE consent_records (
        id              bigserial PRIMARY KEY,
        pseudonym       text NOT NULL REFERENCES participants (pseudonym) ON DELETE CASCADE,
        notice_version  text NOT NULL,
        notice_sha256   text NOT NULL,
        choices         jsonb NOT NULL,
        given_at        timestamptz NOT NULL DEFAULT now(),
        withdrawn_at    timestamptz
    )
    """,
    """
    CREATE TABLE sessions (
        session_id        uuid PRIMARY KEY,
        pseudonym         text NOT NULL REFERENCES participants (pseudonym) ON DELETE CASCADE,
        kind              text NOT NULL CHECK (kind IN ('practice', 'exam')),
        problem_id        text NOT NULL,
        nonce             bytea NOT NULL,
        token_sha256      bytea NOT NULL UNIQUE,
        created_at        timestamptz NOT NULL DEFAULT now(),
        closed_at         timestamptz,
        epoch             integer NOT NULL DEFAULT -1,
        segment_open      boolean NOT NULL DEFAULT false,
        unclean_segments  integer NOT NULL DEFAULT 0,
        next_client_seq   bigint NOT NULL DEFAULT 0,
        next_server_seq   bigint NOT NULL DEFAULT 0,
        next_batch_id     bigint NOT NULL DEFAULT 0,
        head_hash         bytea NOT NULL
    )
    """,
    """
    CREATE TABLE events (
        session_id   uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
        server_seq   bigint NOT NULL,
        epoch        integer NOT NULL,
        client_seq   bigint,
        origin       text NOT NULL CHECK (origin IN ('client', 'server')),
        type         text NOT NULL,
        t_client_us  bigint,
        t_server_us  bigint NOT NULL,
        batch_id     bigint NOT NULL,
        data_ct      bytea NOT NULL,
        prev_hash    bytea NOT NULL,
        hash         bytea NOT NULL,
        PRIMARY KEY (session_id, server_seq),
        UNIQUE (session_id, client_seq)
    )
    """,
    # events is append-only. DELETE is allowed only inside an erasure transaction that has run
    # SELECT set_config('integrity.erasure', 'on', true).
    """
    CREATE FUNCTION events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' AND current_setting('integrity.erasure', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'events is append-only: % blocked', TG_OP;
    END $$
    """,
    """
    CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events
        FOR EACH ROW EXECUTE FUNCTION events_append_only()
    """,
    """
    CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON events
        FOR EACH STATEMENT EXECUTE FUNCTION events_append_only()
    """,
    """
    CREATE TABLE access_log (
        id      bigserial PRIMARY KEY,
        at      timestamptz NOT NULL DEFAULT now(),
        actor   text NOT NULL,
        role    text NOT NULL,
        action  text NOT NULL,
        target  text NOT NULL
    )
    """,
    """
    CREATE FUNCTION log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only: % blocked', TG_TABLE_NAME, TG_OP;
    END $$
    """,
    """
    CREATE TRIGGER access_log_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON access_log
        FOR EACH STATEMENT EXECUTE FUNCTION log_append_only()
    """,
    """
    CREATE TABLE erasure_log (
        id                bigserial PRIMARY KEY,
        pseudonym_sha256  text NOT NULL,
        requested_at      timestamptz NOT NULL,
        completed_at      timestamptz NOT NULL DEFAULT now(),
        actor             text NOT NULL,
        n_sessions        integer NOT NULL,
        n_events          bigint NOT NULL
    )
    """,
    """
    CREATE TRIGGER erasure_log_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON erasure_log
        FOR EACH STATEMENT EXECUTE FUNCTION log_append_only()
    """,
]

DOWNGRADE = [
    "DROP TABLE erasure_log",
    "DROP TABLE access_log",
    "DROP TABLE events",
    "DROP TABLE sessions",
    "DROP TABLE consent_records",
    "DROP TABLE participants",
    "DROP FUNCTION log_append_only()",
    "DROP FUNCTION events_append_only()",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
