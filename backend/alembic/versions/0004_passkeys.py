"""passkeys: fingerprint / face check-in

Adds the passkeys table, the per-service passkey_mode and the passkey_verified flag on
attendance records. Safe to run on a database that already has some of them.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

COLUMNS = [
    # existing services keep working as before until an admin turns the check on
    ("service_templates", "passkey_mode", sa.String(20), False, "OFF"),
    ("attendance_records", "passkey_verified", sa.Boolean(), False, "false"),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not insp.has_table("passkeys"):
        op.create_table(
            "passkeys",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("credential_id", sa.String(512), nullable=False),
            sa.Column("public_key", sa.LargeBinary(), nullable=False),
            sa.Column("alg", sa.Integer(), nullable=False),
            sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("name", sa.String(100), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_passkeys_credential_id", "passkeys", ["credential_id"], unique=True)
        op.create_index("ix_passkeys_user_id", "passkeys", ["user_id"])

    existing: dict[str, set[str]] = {}
    for table, name, type_, nullable, default in COLUMNS:
        if table not in existing:
            existing[table] = {c["name"] for c in insp.get_columns(table)}
        if name not in existing[table]:
            op.add_column(table, sa.Column(name, type_, nullable=nullable, server_default=default))


def downgrade() -> None:
    for table, name, *_ in reversed(COLUMNS):
        names = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        if name in names:
            op.drop_column(table, name)
    if sa.inspect(op.get_bind()).has_table("passkeys"):
        op.drop_table("passkeys")
