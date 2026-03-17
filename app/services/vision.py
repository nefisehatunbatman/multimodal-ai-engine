from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = getattr(settings, "OPENROUTER_API_KEY", None)
VISION_MODEL = getattr(settings, "OPENROUTER_VISION_MODEL", "openai/gpt-4o-mini")


def encode_image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def build_vision_messages(
    image_bytes: bytes,
    mime_type: str,
    question: str,
    context: str,
    history: List[Dict[str, Any]],
    system_prompt: str,
) -> List[Dict[str, Any]]:
    image_b64 = encode_image_to_base64(image_bytes)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]
    messages.extend(history)

    user_content: List[Dict[str, Any]] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
        }
    ]

    if context:
        user_content.append({
            "type": "text",
            "text": (
                "Aşağıda ilgili belge bağlamı verilmiştir.\n"
                "Hem görseli hem de bu bağlamı kullanarak cevap ver.\n\n"
                f"[Bağlam]\n{context}\n\n"
                f"[Soru]\n{question}"
            ),
        })
    else:
        user_content.append({"type": "text", "text": question})

    messages.append({"role": "user", "content": user_content})
    return messages


async def call_openrouter_vision(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is missing")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or VISION_MODEL,
        "messages": messages,
        "temperature": temperature if temperature is not None else 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=f"OpenRouter vision error: {detail}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter vision network error: {e}")