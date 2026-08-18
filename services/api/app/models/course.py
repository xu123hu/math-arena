"""课程模型（F9 双师课堂预处理管线，迭代05 阶段4）

SSOT §4.10 / 星辰指南 §7 / ADR-034：
课程登记 → 预处理（wf_course_preprocess → 本地星火直调 → 固定间隔切段三级降级）
→ 章节切分 + 知识点锚定 + 知识卡抽取 → 结果缓存（course_id 幂等）。
"""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

# 预处理状态
COURSE_STATUS_PENDING = "pending"
COURSE_STATUS_PREPROCESSING = "preprocessing"
COURSE_STATUS_READY = "ready"
COURSE_STATUS_FAILED = "failed"


class Course(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "courses"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("classes.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # ASR 字幕全文（含时间戳标记），预处理输入（SSOT §4.10 ≤20000 字）
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=COURSE_STATUS_PENDING
    )
    # 预处理产物：{chapters:[{title,start_ts,end_ts,summary}], kp_codes:[], knowledge_cards:[{title,content,ts}]}
    preprocess_result: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # 预处理引擎：wf_course_preprocess / spark_direct / fixed_split
    preprocess_engine: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
