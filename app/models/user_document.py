"""
UserDocument modeli — kullanıcı ile WeKnora belge ID'si arasındaki ilişkiyi saklar.
WeKnora title/description alanlarına güvenmek yerine kendi DB'mizde tutuyoruz.
"""
from sqlalchemy import Column, Integer, String, DateTime, func
from app.db.postgres import Base


class UserDocument(Base):
    __tablename__ = "user_documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    knowledge_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())