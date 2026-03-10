from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    user_id: int = Field(gt=0)


class ConversationOut(BaseModel):
    id: int
    user_id: int

    class Config:
        from_attributes = True