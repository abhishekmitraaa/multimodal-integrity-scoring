"""Webcam video chunks per exam session (D-048, a demo feature). The bytes are encrypted files under
the data root; this table is their index. Deleted with the session (erasure, retention).

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE session_videos (
        session_id   uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
        chunk_index  integer NOT NULL CHECK (chunk_index >= 0),
        size         integer NOT NULL CHECK (size > 0),
        sha256       bytea NOT NULL,
        received_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (session_id, chunk_index)
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE session_videos")
