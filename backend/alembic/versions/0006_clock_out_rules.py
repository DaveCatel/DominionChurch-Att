"""clock-out rules: remember how far from the church a member clocked out

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

COLUMNS = [
    ("attendance_records", "clock_out_distance_m", sa.Integer()),
    ("attendance_records", "clock_out_accuracy_m", sa.Float()),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns("attendance_records")}
    for table, name, type_ in COLUMNS:
        if name not in existing:
            op.add_column(table, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("attendance_records")}
    for table, name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column(table, name)
