from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.message import MessageCreate, MessageOut

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def create_message(payload: MessageCreate, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == payload.conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = Message(
        conversation_id=payload.conversation_id,
        role=payload.role.value,
        content=payload.content,
        meta=payload.meta,
    )

    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/", response_model=list[MessageOut])
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
        .all()
    )