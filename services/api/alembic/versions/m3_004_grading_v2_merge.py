"""Merge the existing identity and Grading V2 migration branches.

This preserves databases that applied either branch before Grading V2 was
introduced, while giving fresh installs a single deterministic head.

Revision ID: m3_004_grading_v2_merge
Revises: auth_001_unified_identity, m3_003_grading_v2_workspace
Create Date: 2026-08-24
"""

revision = "m3_004_grading_v2_merge"
down_revision = ("auth_001_unified_identity", "m3_003_grading_v2_workspace")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
