"""情景记忆模型"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, SmallInteger, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class EpisodicMemory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "episodic_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1024), nullable=False)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    kp_ids: Mapped[list] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
