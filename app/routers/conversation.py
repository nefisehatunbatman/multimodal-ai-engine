from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationOut

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    # User var mı kontrol et
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Conversation oluştur
    conversation = Conversation(user_id=payload.user_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


@router.get("/", response_model=list[ConversationOut])
def list_conversations(user_id: int, db: Session = Depends(get_db)):
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.id.asc())
        .all()
    )