from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)

WEKNORA_HOST = getattr(settings, "WEKNORA_APP_HOST", "localhost")
WEKNORA_PORT = int(getattr(settings, "WEKNORA_APP_PORT", 8080))
WEKNORA_API_KEY = getattr(settings, "WEKNORA_API_KEY", None)
WEKNORA_KB_ID = getattr(settings, "WEKNORA_KB_ID", None)

WEKNORA_BASE_URL = f"http://{WEKNORA_HOST}:{WEKNORA_PORT}"

ALLOWED_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _weknora_headers() -> dict[str, str]:
    return {"X-API-Key": WEKNORA_API_KEY or ""}

async def ingest_file_to_weknora(file: UploadFile) -> dict:
    """
    Dosyayı WeKnora knowledge base'e yükler.
    WeKnora içinde: parse → chunk → Ollama embed → Qdrant'a yaz
    """
    if not WEKNORA_API_KEY:
        raise RuntimeError("WEKNORA_API_KEY is missing in environment")
    if not WEKNORA_KB_ID:
        raise RuntimeError("WEKNORA_KB_ID is missing in environment")

    suffix = Path(file.filename or "").suffix.lower()
    mime_type = ALLOWED_MIME_TYPES.get(suffix, "application/octet-stream")

    file_bytes = await file.read()
    if not file_bytes:
        raise RuntimeError("Yüklenen dosya boş")

    upload_url = f"{WEKNORA_BASE_URL}/api/v1/knowledge-bases/{WEKNORA_KB_ID}/knowledge/file"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                upload_url,
                headers=_weknora_headers(),
                files={"file": (file.filename, file_bytes, mime_type)},
            )
            resp.raise_for_status()
            data = resp.json()

    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise RuntimeError(
            f"WeKnora upload error (status={e.response.status_code}): {detail}"
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"WeKnora unreachable: {e}")

    logger.info(
        "WeKnora ingestion complete: file=%s kb_id=%s",
        file.filename,
        WEKNORA_KB_ID,
    )

    return {
        "ok": True,
        "filename": file.filename,
        "kb_id": WEKNORA_KB_ID,
        "source": "weknora",
        "weknora_response": data,
    }