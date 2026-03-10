from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class MessageCreate(BaseModel):
    conversation_id: int = Field(gt=0)
    role: MessageRole
    content: str = Field(min_length=1)
    meta: Optional[Dict[str, Any]] = None


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    role: MessageRole
    content: str
    meta: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True