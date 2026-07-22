"""消息模型"""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Message(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_msg_id", name="uq_messages_conv_client"),
        Index(
            "idx_messages_conv",
            "conversation_id",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), nullable=False
    )
    client_msg_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    envelope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    skill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
