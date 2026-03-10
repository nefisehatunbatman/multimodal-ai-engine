from pydantic import BaseModel
from typing import Any, Dict, Optional


class VisionChatResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    assistant_text: str
    vision_model: str