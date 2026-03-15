from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: int = Field(gt=0)
    message: str = Field(min_length=1)
    meta: Dict[str, Any] = Field(default_factory=dict)
    document_ids: Optional[List[str]] = Field(
        default=None,
        description="Sadece bu belge ID'lerinde ara. None ise tüm KB taranır.",
    )


class ChatResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    assistant_text: str


class ChatStreamResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    stream_topic: str
    done_topic: str