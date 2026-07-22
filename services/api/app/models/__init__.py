"""SQLAlchemy 模型包

__init__.py 里 import 全部 model 供 alembic autogenerate。
"""

from app.models.ai_call import AICall
from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.chunk import Chunk
from app.models.class_ import Class
from app.models.class_member import ClassMember
from app.models.conversation import Conversation
from app.models.episodic_memory import EpisodicMemory
from app.models.event import Event
from app.models.knowledge_doc import KnowledgeDoc
from app.models.knowledge_point import KnowledgePoint
from app.models.message import Message
from app.models.role_binding import RoleBinding
from app.models.skill import Skill
from app.models.skill_run import SkillRun
from app.models.user import User
from app.models.user_profile import UserProfile

__all__ = [
    "Base",
    "SoftDeleteMixin",
    "TimestampMixin",
    "User",
    "RoleBinding",
    "Class",
    "ClassMember",
    "Conversation",
    "Message",
    "UserProfile",
    "EpisodicMemory",
    "KnowledgePoint",
    "KnowledgeDoc",
    "Chunk",
    "Skill",
    "SkillRun",
    "AICall",
    "AICall",
    "Event",
]
