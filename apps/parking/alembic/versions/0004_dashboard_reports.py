"""BotConnector Parking M10-M12 — site capacity, role expansion.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- M10: site capacity (occupancy derives from active sessions) --------
    op.add_column("parking_site", sa.Column("capacity_total", sa.Integer(), nullable=True))
    op.add_column("parking_site", sa.Column("capacity_motorcycle", sa.Integer(), nullable=True))
    op.add_column("parking_site", sa.Column("capacity_car", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_parking_site_capacity_total_nonneg", "parking_site", "capacity_total IS NULL OR capacity_total >= 0"
    )
    op.create_check_constraint(
        "ck_parking_site_capacity_motorcycle_nonneg", "parking_site",
        "capacity_motorcycle IS NULL OR capacity_motorcycle >= 0",
    )
    op.create_check_constraint(
        "ck_parking_site_capacity_car_nonneg", "parking_site", "capacity_car IS NULL OR capacity_car >= 0"
    )

    # ---- M10: expand operator roles (OWNER / MANAGER / VIEWER) --------------
    op.drop_constraint("ck_parking_operator_role_allowed", "parking_operator", type_="check")
    op.create_check_constraint(
        "ck_parking_operator_role_allowed", "parking_operator",
        "role IN ('OWNER','ADMIN','MANAGER','SUPERVISOR','OPERATOR','VIEWER')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_parking_operator_role_allowed", "parking_operator", type_="check")
    op.create_check_constraint(
        "ck_parking_operator_role_allowed", "parking_operator",
        "role IN ('ADMIN','SUPERVISOR','OPERATOR')",
    )
    op.drop_constraint("ck_parking_site_capacity_car_nonneg", "parking_site", type_="check")
    op.drop_constraint("ck_parking_site_capacity_motorcycle_nonneg", "parking_site", type_="check")
    op.drop_constraint("ck_parking_site_capacity_total_nonneg", "parking_site", type_="check")
    op.drop_column("parking_site", "capacity_car")
    op.drop_column("parking_site", "capacity_motorcycle")
    op.drop_column("parking_site", "capacity_total")
