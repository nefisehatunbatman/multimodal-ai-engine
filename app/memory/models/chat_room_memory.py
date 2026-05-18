"""
app/memory/models/chat_room_memory.py

L1 Yerel Hafıza — PostgreSQL tablosu.

Tablo: chat_room_memory
- Her chat odası (conversation) için bir satır tutulur.
- summary: JSONB — {"text": "...", "generated_at_tokens": 1234}
- key_facts: JSONB array — [{"role": "user", "content": "...", "score": 0.8, "tags": [...]}]
- l2_pending: L1 güncellendiğinde True yapılır, L2 işleyince False'a çekilir.

Alembic kullanıyorsan:
    alembic revision --autogenerate -m "add_chat_room_memory"
    alembic upgrade head

Kullanmıyorsan main.py'deki Base.metadata.create_all() otomatik oluşturur.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class ChatRoomMemory(Base):
    __tablename__ = "chat_room_memory"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_chat_room_memory_conversation"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Hangi konuşmaya ait
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Hangi kullanıcıya ait (L2 sorgularını hızlandırır)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── L1 Özet ───────────────────────────────────────────────────────────────
    # {"text": "...", "generated_at_tokens": 1234}
    summary = Column(JSONB, nullable=True, default=None)

    # Önemli noktalar — ImportanceScorer çıktısı
    # [{"role": "user", "content": "...", "score": 0.8, "tags": ["decision"]}]
    key_facts = Column(JSONB, nullable=True, default=list)

    # ── Token takibi ───────────────────────────────────────────────────────────
    # Bu konuşmada görülen toplam (kümülatif) token tahmini
    total_tokens = Column(BigInteger, nullable=False, default=0)

    # Son özet üretildiğindeki token değeri
    # Bir sonraki özet için: total_tokens - last_summary_at_tokens >= L1_INCREMENT_TOKENS
    last_summary_at_tokens = Column(BigInteger, nullable=False, default=0)

    # Kaçıncı özet versiyonu (0 = henüz üretilmedi)
    summary_version = Column(Integer, nullable=False, default=0)

    # ── L2 sinyali ────────────────────────────────────────────────────────────
    # True → L1 güncellendi, L2 worker henüz işlemedi
    l2_pending = Column(Boolean, nullable=False, default=False)

    # ── Zaman damgaları ────────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── İlişkiler (lazy — döngüsel import riski yok) ──────────────────────────
    conversation = relationship("Conversation", backref="memory", lazy="select", viewonly=True)

    def __repr__(self) -> str:
        return (
            f"<ChatRoomMemory id={self.id} "
            f"conv={self.conversation_id} "
            f"tokens={self.total_tokens} "
            f"version={self.summary_version}>"
        )