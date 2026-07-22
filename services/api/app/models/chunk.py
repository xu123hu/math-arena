"""切片模型（知识库域）

TODO: pgvector 安装后，将 embedding 列类型从 Text 改为 Vector(1024)，
      并创建 HNSW 索引。
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Chunk(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "chunks"
    # TODO: pgvector 可用后取消注释以下索引
    # __table_args__ = (
    #     Index("idx_chunks_embedding", "embedding",
    #           postgresql_using="hnsw",
    #           postgresql_with={"m": 16, "ef_construction": 64},
    #           postgresql_ops={"embedding": "vector_cosine_ops"}),
    # )

    doc_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_docs.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # TODO: 改为 Vector(1024) — 需要 pgvector 扩展
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    kp_ids: Mapped[list] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
