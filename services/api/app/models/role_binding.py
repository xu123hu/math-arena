"""角色绑定模型"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class RoleBinding(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "role_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_role_bindings_user_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    org_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
