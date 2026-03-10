from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.db.postgres import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False, unique=True, index=True)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")