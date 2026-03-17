import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.deps import get_db
from app.db.postgres import SessionLocal
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.chat import ChatStreamResponse
from app.services.rag import retrieve_context
from app.services.vision import build_vision_messages, call_openrouter_vision, VISION_MODEL
from app.services.mqtt import (
    get_mqtt_client,
    publish_token,
    publish_done,
    publish_error,
    get_stream_topic,
    get_done_topic,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

DEFAULT_SYSTEM_PROMPT = getattr(settings, "DEFAULT_SYSTEM_PROMPT", None) or "You are a helpful assistant."
MAX_HISTORY_MESSAGES = int(getattr(settings, "MAX_HISTORY_MESSAGES", 6))
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def build_base_history_messages(history: List[Message]) -> List[Dict[str, str]]:
    llm_messages: List[Dict[str, str]] = []
    for m in history:
        if m.role in ("user", "assistant") and m.content:
            llm_messages.append({"role": m.role, "content": m.content})
    return llm_messages


def build_system_prompt() -> str:
    base = DEFAULT_SYSTEM_PROMPT.strip()
    rag_rules = """
Sen yardımcı bir asistansın. Sana belge bağlamı sağlandığında önce onu kullan.
Belgede bilgi yoksa veya yetersizse kendi bilginle cevap ver.
Kullanıcıya her zaman faydalı ve dolu bir cevap sun.
""".strip()
    return f"{base}\n\n{rag_rules}"


def _safe_extract_assistant_text(data: Dict[str, Any]) -> str:
    try:
        choices = data.get("choices")
        if not choices:
            raise KeyError("choices is missing/empty")

        msg = choices[0].get("message")
        if not msg:
            raise KeyError("choices[0].message is missing")

        content = msg.get("content")
        if content is None:
            raise KeyError("choices[0].message.content is missing")

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return "\n".join(parts)

        return str(content).strip()

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM response parse error: {e}")


def _error_to_meta(e: Exception) -> Dict[str, Any]:
    text = str(e)
    if len(text) > 2000:
        text = text[:2000] + "...(truncated)"
    return {
        "error_type": e.__class__.__name__,
        "error_message": text,
    }


def _get_conversation_or_403(
    conversation_id: int,
    current_user: User,
    db: Session,
) -> Conversation:
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return conv


async def _maybe_generate_title(conv: Conversation, message: str, db: Session) -> None:
    if conv.title and conv.title != "Yeni Sohbet":
        return

    if not settings.OPENROUTER_API_KEY:
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENROUTER_MODEL_PRIMARY or "openai/gpt-4o-mini",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Kullanıcının mesajından 3-6 kelimelik kısa bir sohbet başlığı üret. "
                                "Sadece başlığı yaz, başka hiçbir şey yazma. Nokta veya tırnak kullanma."
                            ),
                        },
                        {"role": "user", "content": message[:300]},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 20,
                },
            )
            r.raise_for_status()
            title = r.json()["choices"][0]["message"]["content"].strip()
            if title:
                conv.title = title[:100]
                db.add(conv)
                db.commit()
                logger.info("Auto-title generated for conversation %d: %s", conv.id, title)

    except Exception as e:
        logger.warning("Auto-title generation failed: %s", e)


def _parse_document_ids(document_ids_str: str) -> Optional[List[str]]:
    if not document_ids_str.strip():
        return None
    return [d.strip() for d in document_ids_str.split(",") if d.strip()]


async def call_openrouter_stream(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
):
    if not settings.OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is missing in .env")

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model or settings.OPENROUTER_MODEL_PRIMARY or "openai/gpt-4o-mini",
                "messages": messages,
                "temperature": temperature if temperature is not None else 0.2,
                "stream": True,
            },
        ) as r:
            r.raise_for_status()

            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()

                if data_str == "[DONE]":
                    break

                if not data_str:
                    continue

                try:
                    chunk = json.loads(data_str)
                    token = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                    if token:
                        yield token
                except Exception:
                    continue


def _build_text_messages(
    history: List[Message],
    message: str,
    context: str,
) -> List[Dict[str, Any]]:
    llm_history = build_base_history_messages(history)

    if llm_history and llm_history[-1]["role"] == "user":
        llm_history = llm_history[:-1]

    if context:
        user_content = (
            "Aşağıda belge bağlamı verilmiştir.\n"
            "Kullanıcının sorusuna birebir cevap olmasa bile, bağlamdaki ilgili tüm bilgileri kullanıcıya sun.\n"
            "Bağlamda hiç ilgili bilgi yoksa kendi genel bilginle cevap ver.\n\n"
            f"[Bağlam]\n{context}\n\n"
            f"[Soru]\n{message}"
        )
    else:
        user_content = (
            "Belge bağlamı bulunamadı.\n"
            "Kendi bilginle normal bir asistan gibi cevap ver.\n\n"
            f"[Soru]\n{message}"
        )

    return [
        {"role": "system", "content": build_system_prompt()},
        *llm_history,
        {"role": "user", "content": user_content},
    ]


async def _build_llm_messages(
    history: List[Message],
    message: str,
    context: str,
    image: Optional[UploadFile],
) -> tuple[List[Dict[str, Any]], bool]:
    llm_history = build_base_history_messages(history)

    if llm_history and llm_history[-1]["role"] == "user":
        llm_history = llm_history[:-1]

    if image is not None:
        mime = image.content_type or ""

        if mime not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Desteklenen görsel formatları: {', '.join(ALLOWED_IMAGE_TYPES)}. Gelen: {mime}",
            )

        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Görsel dosyası boş")

        return build_vision_messages(
            image_bytes=image_bytes,
            mime_type=mime,
            question=message,
            context=context,
            history=llm_history,
            system_prompt=build_system_prompt(),
        ), True

    return _build_text_messages(history, message, context), False


async def run_chat_streaming_task(
    conversation_id: int,
    assistant_message_id: int,
    llm_messages: List[Dict[str, Any]],
    used_model: str,
    context: str,
    is_vision: bool,
    selected_model: Optional[str],
    temperature: Optional[float],
):
    db: Session = SessionLocal()

    try:
        assistant_msg = (
            db.query(Message)
            .filter(Message.id == assistant_message_id)
            .first()
        )

        if not assistant_msg:
            logger.warning("Assistant message not found: %s", assistant_message_id)
            return

        full_text = ""
        start = time.perf_counter()

        if is_vision:
            data = await call_openrouter_vision(
                llm_messages,
                model=selected_model,
                temperature=temperature,
            )
            full_text = _safe_extract_assistant_text(data)
            latency_ms = int((time.perf_counter() - start) * 1000)

            async with get_mqtt_client() as mqtt:
                await publish_done(
                    mqtt,
                    conversation_id,
                    assistant_message_id,
                    full_text,
                    {
                        "model": used_model,
                        "latency_ms": latency_ms,
                        "rag_context_used": bool(context),
                    },
                )

        else:
            async with get_mqtt_client() as mqtt:
                async for token in call_openrouter_stream(
                    llm_messages,
                    model=selected_model,
                    temperature=temperature,
                ):
                    full_text += token
                    await publish_token(
                        mqtt,
                        conversation_id,
                        assistant_message_id,
                        token,
                    )

                latency_ms = int((time.perf_counter() - start) * 1000)

                await publish_done(
                    mqtt,
                    conversation_id,
                    assistant_message_id,
                    full_text,
                    {
                        "model": used_model,
                        "latency_ms": latency_ms,
                        "rag_context_used": bool(context),
                    },
                )

        assistant_msg.content = full_text
        assistant_msg.meta = {
            **(assistant_msg.meta or {}),
            "status": "completed",
            "model": used_model,
            "latency_ms": latency_ms,
        }
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

    except Exception as e:
        logger.exception(
            "Background chat streaming error for conversation_id=%d, assistant_message_id=%d: %s",
            conversation_id,
            assistant_message_id,
            e,
        )

        try:
            async with get_mqtt_client() as mqtt:
                await publish_error(
                    mqtt,
                    conversation_id,
                    assistant_message_id,
                    str(e),
                )
        except Exception as mqtt_err:
            logger.warning("MQTT error publish failed: %s", mqtt_err)

        assistant_msg = (
            db.query(Message)
            .filter(Message.id == assistant_message_id)
            .first()
        )
        if assistant_msg:
            assistant_msg.meta = {
                **(assistant_msg.meta or {}),
                "status": "failed",
                **_error_to_meta(e),
            }
            db.add(assistant_msg)
            db.commit()

    finally:
        db.close()


@router.post("/", response_model=ChatStreamResponse, status_code=status.HTTP_200_OK)
async def chat(
    conversation_id: int = Form(...),
    message: str = Form(...),
    document_ids: str = Form(default=""),
    model: Optional[str] = Form(default=None),
    temperature: Optional[float] = Form(default=None),
    image: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = _get_conversation_or_403(conversation_id, current_user, db)
    parsed_doc_ids = _parse_document_ids(document_ids)

    user_msg = Message(
        conversation_id=conversation_id,
        role="user",
        content=message,
        meta={
            "has_image": image is not None,
            **(
                {
                    "image_filename": image.filename,
                    "image_mime_type": image.content_type,
                }
                if image
                else {}
            ),
        },
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    await _maybe_generate_title(conv, message, db)

    history = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )[::-1]

    context = await retrieve_context(message, document_ids=parsed_doc_ids)
    llm_messages, is_vision = await _build_llm_messages(history, message, context, image)

    used_model = model or (VISION_MODEL if is_vision else None) or settings.OPENROUTER_MODEL_PRIMARY or "openai/gpt-4o-mini"

    assistant_msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content="",
        meta={
            "status": "in_progress",
            "source": "openrouter_vision" if is_vision else "openrouter_stream",
            "model": used_model,
            "rag_context_used": bool(context),
            "rag_context_length": len(context) if context else 0,
        },
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    stream_topic = get_stream_topic(conversation_id, assistant_msg.id)
    done_topic = get_done_topic(conversation_id, assistant_msg.id)

    asyncio.create_task(
        run_chat_streaming_task(
            conversation_id=conversation_id,
            assistant_message_id=assistant_msg.id,
            llm_messages=llm_messages,
            used_model=used_model,
            context=context,
            is_vision=is_vision,
            selected_model=model,
            temperature=temperature,
        )
    )

    return ChatStreamResponse(
        conversation_id=conversation_id,
        user_message_id=user_msg.id,
        assistant_message_id=assistant_msg.id,
        stream_topic=stream_topic,
        done_topic=done_topic,
    )