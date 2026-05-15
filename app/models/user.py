"""
User modeli — L2 global kullanıcı hafızası kolonu eklendi.
Mevcut tabloya sadece global_memory JSONB kolonu ekleniyor;
diğer alanlar değişmiyor.

Alembic kullanıyorsanız aşağıdaki migration'ı çalıştırın:
    ALTER TABLE users ADD COLUMN IF NOT EXISTS global_memory JSONB;
    ALTER TABLE users ADD COLUMN IF NOT EXISTS l2_updated_at TIMESTAMPTZ;
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.db.postgres import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)

    # ── L2 Global Kullanıcı Hafızası ───────────────────────────────────────
    # Tüm konuşmalardan damıtılan uzun vadeli kullanıcı profili.
    # Yapı örneği:
    # {
    #   "interests": ["makine öğrenmesi", "python"],
    #   "decisions": ["PostgreSQL tercih etti", "FastAPI kullanıyor"],
    #   "style": "teknik, detaylı yanıt istiyor",
    #   "last_topics": ["RAG mimarisi", "token yönetimi"],
    #   "updated_at": "2026-05-14T10:00:00Z"
    # }
    global_memory = Column(JSONB, nullable=True, default=dict)

    # L2'nin en son ne zaman güncellendiği
    l2_updated_at = Column(DateTime(timezone=True), nullable=True)

    conversations = relationship("Conversation", back_populates="user")