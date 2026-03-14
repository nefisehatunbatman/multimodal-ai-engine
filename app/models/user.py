from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.db.postgres import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)

    conversations = relationship("Conversation", back_populates="user")