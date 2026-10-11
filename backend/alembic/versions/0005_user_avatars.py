"""profile photos kept in the database

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("user_avatars"):
        return  # already created by init_db
    op.create_table(
        "user_avatars",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("token", sa.String(40), nullable=False),
        sa.Column("content_type", sa.String(30), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_avatars_token", "user_avatars", ["token"], unique=True)


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("user_avatars"):
        op.drop_table("user_avatars")
