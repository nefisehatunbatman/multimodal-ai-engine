import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.deps import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.routers.chat import (
    MAX_HISTORY_MESSAGES,
    build_base_history_messages,
    build_system_prompt,
    _safe_extract_assistant_text,
    _error_to_meta,
)
from app.schemas.vision import VisionChatResponse
from app.services.rag import retrieve_context
from app.services.vision import call_openrouter_vision, build_vision_messages, VISION_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vision", tags=["vision"])

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def validate_image(file: UploadFile) -> str:
    mime = file.content_type or ""
    if mime not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenen formatlar: {', '.join(ALLOWED_IMAGE_TYPES.keys())}. Gelen: {mime}",
        )
    return mime


@router.post("/chat", response_model=VisionChatResponse, status_code=status.HTTP_200_OK)
async def vision_chat(
    conversation_id: int = Form(...),
    message: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Conversation var mı kontrol et
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Görsel formatını doğrula
    mime_type = validate_image(image)
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Görsel dosyası boş")

    # Kullanıcı mesajını kaydet
    user_msg = Message(
        conversation_id=conversation_id,
        role="user",
        content=message,
        meta={
            "has_image": True,
            "image_filename": image.filename,
            "image_mime_type": mime_type,
        },
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Konuşma geçmişini al
    history = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )[::-1]

    # RAG context al
    context = await retrieve_context(message)

    # History'den son user mesajını çıkar (zaten vision message olarak ekleyeceğiz)
    llm_history = build_base_history_messages(history)
    if llm_history and llm_history[-1]["role"] == "user":
        llm_history = llm_history[:-1]

    # System prompt
    system_prompt = build_system_prompt()

    # Vision mesajlarını oluştur
    llm_messages = build_vision_messages(
        image_bytes=image_bytes,
        mime_type=mime_type,
        question=message,
        context=context,
        history=llm_history,
        system_prompt=system_prompt,
    )

    # Assistant mesajını önceden kaydet
    assistant_msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content="",
        meta={
            "status": "in_progress",
            "source": "openrouter_vision",
            "model": VISION_MODEL,
            "history_size": len(history),
            "rag_context_used": bool(context),
            "rag_context_length": len(context) if context else 0,
        },
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    start = time.perf_counter()

    try:
        data = await call_openrouter_vision(llm_messages)
        latency_ms = int((time.perf_counter() - start) * 1000)

        assistant_text = _safe_extract_assistant_text(data)
        usage = data.get("usage") or {}

        assistant_msg.content = assistant_text
        assistant_msg.meta = {
            **(assistant_msg.meta or {}),
            "status": "completed",
            "latency_ms": latency_ms,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        return VisionChatResponse(
            conversation_id=conversation_id,
            user_message_id=user_msg.id,
            assistant_message_id=assistant_msg.id,
            assistant_text=assistant_text,
            vision_model=VISION_MODEL,
        )

    except HTTPException as he:
        latency_ms = int((time.perf_counter() - start) * 1000)
        assistant_msg.meta = {
            **(assistant_msg.meta or {}),
            "status": "failed",
            "latency_ms": latency_ms,
            **_error_to_meta(he),
        }
        db.add(assistant_msg)
        db.commit()
        raise

    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        assistant_msg.meta = {
            **(assistant_msg.meta or {}),
            "status": "failed",
            "latency_ms": latency_ms,
            **_error_to_meta(e),
        }
        db.add(assistant_msg)
        db.commit()
        raise HTTPException(status_code=500, detail="Unexpected server error")