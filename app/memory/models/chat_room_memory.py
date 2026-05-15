from sqlalchemy import Column, Integer, ForeignKey, DateTime, BigInteger, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.postgres import Base


class ChatRoomMemory(Base):
    __tablename__ = "chat_room_memory"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary = Column(JSONB, nullable=True)
    key_facts = Column(JSONB, nullable=True, default=list)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    last_summary_at_tokens = Column(BigInteger, nullable=False, default=0)
    summary_version = Column(Integer, nullable=False, default=0)
    l2_pending = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)