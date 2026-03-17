from pydantic import BaseModel


class ChatStreamResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    stream_topic: str
    done_topic: str