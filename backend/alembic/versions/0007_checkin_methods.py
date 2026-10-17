"""check-in methods: location is always required, then the code OR a fingerprint

Old settings are mapped onto the new ones:
  verification_mode CODE (code only, no location)  ->  CODE_LOCATION (location is now always checked)
  passkey_mode      IF_ENROLLED                    ->  OPTIONAL (code or fingerprint, the member's choice)

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE service_templates SET verification_mode = 'CODE_LOCATION' WHERE verification_mode = 'CODE'")
    op.execute("UPDATE service_templates SET passkey_mode = 'OPTIONAL' WHERE passkey_mode = 'IF_ENROLLED'")


def downgrade() -> None:
    pass  # the old values cannot be told apart from the new ones any more
