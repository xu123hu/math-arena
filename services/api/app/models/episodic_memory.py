"""情景记忆模型

TODO: pgvector 安装后，将 embedding 列类型从 Text 改为 Vector(1024)，
      并创建 HNSW 索引。运行 install-pgvector.ps1 后更新此模型。
"""

import uuid

from sqlalchemy import ForeignKey, SmallInteger, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class EpisodicMemory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "episodic_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # TODO: 改为 Vector(1024) — 需要 pgvector 扩展
    embedding: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    kp_ids: Mapped[list] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
