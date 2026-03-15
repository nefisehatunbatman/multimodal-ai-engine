import logging
import time
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.deps import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse, ChatStreamResponse
from app.services.rag import retrieve_context
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
    return {"error_type": e.__class__.__name__, "error_message": text}


async def call_openrouter(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    if not settings.OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is missing in .env")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENROUTER_MODEL_PRIMARY or "openai/gpt-4o-mini",
        "messages": messages,
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=f"OpenRouter error: {detail}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter network error: {e}")


async def call_openrouter_stream(messages: List[Dict[str, str]]):
    if not settings.OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is missing in .env")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENROUTER_MODEL_PRIMARY or "openai/gpt-4o-mini",
        "messages": messages,
        "temperature": 0.2,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
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
                    import json
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content")
                    if token:
                        yield token
                except Exception:
                    continue


def _build_llm_messages(
    history: List[Message],
    message: str,
    context: str,
) -> List[Dict[str, str]]:
    llm_history = build_base_history_messages(history)
    if llm_history and llm_history[-1]["role"] == "user":
        llm_history = llm_history[:-1]

    system_prompt = build_system_prompt()

    if context:
        augmented_user_message = (
            "Aşağıda belge bağlamı verilmiştir.\n"
            "Kullanıcının sorusuna birebir cevap olmasa bile, bağlamdaki ilgili tüm bilgileri kullanıcıya sun.\n"
            "Örneğin kullanıcı 'toplam maliyet' soruyorsa ama bağlamda 'toplam gelir' varsa, "
            "onu da göster ve 'belgede maliyet yok ama toplam gelir şu' şeklinde cevap ver.\n"
            "Bağlamdaki finansal, sayısal veya ilgili tüm verileri mutlaka paylaş.\n"
            "Bağlamda hiç ilgili bilgi yoksa kendi genel bilginle cevap ver.\n\n"
            f"[Bağlam]\n{context}\n\n"
            f"[Soru]\n{message}"
        )
    else:
        augmented_user_message = (
            "Belge bağlamı bulunamadı.\n"
            "Kendi bilginle normal bir asistan gibi cevap ver.\n\n"
            f"[Soru]\n{message}"
        )

    return [
        {"role": "system", "content": system_prompt},
        *llm_history,
        {"role": "user", "content": augmented_user_message},
    ]


@router.post("/", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = db.query(Conversation).filter(Conversation.id == payload.conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_msg = Message(
        conversation_id=payload.conversation_id,
        role="user",
        content=payload.message,
        meta=payload.meta,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    history = (
        db.query(Message)
        .filter(Message.conversation_id == payload.conversation_id)
        .order_by(Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )[::-1]

    context = await retrieve_context(payload.message, document_ids=payload.document_ids)
    llm_messages = _build_llm_messages(history, payload.message, context)

    assistant_msg = Message(
        conversation_id=payload.conversation_id,
        role="assistant",
        content="",
        meta={
            "status": "in_progress",
            "source": "openrouter",
            "history_size": len(history),
            "llm_message_count": len(llm_messages),
            "max_history_messages": MAX_HISTORY_MESSAGES,
            "rag_context_used": bool(context),
            "rag_context_length": len(context) if context else 0,
        },
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    start = time.perf_counter()

    try:
        data = await call_openrouter(llm_messages)
        latency_ms = int((time.perf_counter() - start) * 1000)
        assistant_text = _safe_extract_assistant_text(data)
        usage = data.get("usage") or {}
        used_model = data.get("model") or (settings.OPENROUTER_MODEL_PRIMARY or "openai/gpt-4o-mini")

        assistant_msg.content = assistant_text
        assistant_msg.meta = {
            **(assistant_msg.meta or {}),
            "status": "completed",
            "model": used_model,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        return ChatResponse(
            conversation_id=payload.conversation_id,
            user_message_id=user_msg.id,
            assistant_message_id=assistant_msg.id,
            assistant_text=assistant_text,
        )

    except HTTPException as he:
        latency_ms = int((time.perf_counter() - start) * 1000)
        assistant_msg.meta = {**(assistant_msg.meta or {}), "status": "failed", "latency_ms": latency_ms, **_error_to_meta(he)}
        db.add(assistant_msg)
        db.commit()
        raise

    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        assistant_msg.meta = {**(assistant_msg.meta or {}), "status": "failed", "latency_ms": latency_ms, **_error_to_meta(e)}
        db.add(assistant_msg)
        db.commit()
        raise HTTPException(status_code=500, detail="Unexpected server error")


@router.post("/stream", response_model=ChatStreamResponse, status_code=status.HTTP_200_OK)
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = db.query(Conversation).filter(Conversation.id == payload.conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_msg = Message(
        conversation_id=payload.conversation_id,
        role="user",
        content=payload.message,
        meta=payload.meta,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    history = (
        db.query(Message)
        .filter(Message.conversation_id == payload.conversation_id)
        .order_by(Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )[::-1]

    context = await retrieve_context(payload.message, document_ids=payload.document_ids)
    llm_messages = _build_llm_messages(history, payload.message, context)

    assistant_msg = Message(
        conversation_id=payload.conversation_id,
        role="assistant",
        content="",
        meta={
            "status": "in_progress",
            "source": "openrouter_stream",
            "rag_context_used": bool(context),
            "rag_context_length": len(context) if context else 0,
        },
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    stream_topic = get_stream_topic(payload.conversation_id, assistant_msg.id)
    done_topic = get_done_topic(payload.conversation_id, assistant_msg.id)

    full_text = ""
    start = time.perf_counter()

    try:
        async with await get_mqtt_client() as mqtt:
            async for token in call_openrouter_stream(llm_messages):
                full_text += token
                await publish_token(mqtt, payload.conversation_id, assistant_msg.id, token)

            latency_ms = int((time.perf_counter() - start) * 1000)

            await publish_done(
                mqtt,
                payload.conversation_id,
                assistant_msg.id,
                full_text,
                {
                    "model": settings.OPENROUTER_MODEL_PRIMARY,
                    "latency_ms": latency_ms,
                    "rag_context_used": bool(context),
                },
            )

        assistant_msg.content = full_text
        assistant_msg.meta = {
            **(assistant_msg.meta or {}),
            "status": "completed",
            "model": settings.OPENROUTER_MODEL_PRIMARY,
            "latency_ms": latency_ms,
        }
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        return ChatStreamResponse(
            conversation_id=payload.conversation_id,
            user_message_id=user_msg.id,
            assistant_message_id=assistant_msg.id,
            stream_topic=stream_topic,
            done_topic=done_topic,
        )

    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        try:
            async with await get_mqtt_client() as mqtt:
                await publish_error(mqtt, payload.conversation_id, assistant_msg.id, str(e))
        except Exception:
            pass
        assistant_msg.meta = {**(assistant_msg.meta or {}), "status": "failed", "latency_ms": latency_ms, **_error_to_meta(e)}
        db.add(assistant_msg)
        db.commit()
        raise HTTPException(status_code=500, detail="Streaming error")