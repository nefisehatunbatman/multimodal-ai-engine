from __future__ import annotations

import hashlib
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

ALLOWED_IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Hash title'a gömülür: "dosya.pdf [hash:abc123...]"
# WeKnora description alanını otomatik eziyor, title daha güvenilir
HASH_TAG = "[hash:"
HASH_TAG_END = "]"


def _weknora_headers() -> dict[str, str]:
    return {"X-API-Key": WEKNORA_API_KEY or ""}


def _compute_hash(data: bytes) -> str:
    """Dosya içeriğinin SHA256 hash'ini hesaplar."""
    return hashlib.sha256(data).hexdigest()


def _embed_hash_in_title(title: str, content_hash: str) -> str:
    """Title'a hash tag ekler: 'dosya.pdf [hash:abc123]'"""
    return f"{title} {HASH_TAG}{content_hash[:16]}{HASH_TAG_END}"


async def _get_existing_hashes(client: httpx.AsyncClient) -> set[str]:
    """
    KB'deki tüm belgelerin title alanlarından hash'leri toplar.
    WeKnora description'ı otomatik ezdiği için title kullanıyoruz.
    Duplicate tespiti için kullanılır.
    """
    hashes: set[str] = set()
    page = 1
    page_size = 100

    while True:
        url = (
            f"{WEKNORA_BASE_URL}/api/v1/knowledge-bases/{WEKNORA_KB_ID}/knowledge"
            f"?page={page}&page_size={page_size}"
        )
        try:
            resp = await client.get(url, headers=_weknora_headers())
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Hash listesi alınamadı: %s", e)
            break

        items = data.get("data") or []
        total = data.get("total", 0)

        for item in items:
            title = item.get("title") or ""
            # title içinde [hash:xxxx] formatını ara
            if HASH_TAG in title:
                try:
                    start = title.index(HASH_TAG) + len(HASH_TAG)
                    end = title.index(HASH_TAG_END, start)
                    hashes.add(title[start:end])
                except ValueError:
                    pass

        # Tüm sayfaları gezdik mi?
        if page * page_size >= total or not items:
            break
        page += 1

    return hashes


async def ingest_file_to_weknora(file: UploadFile) -> dict:
    """
    Dosyayı WeKnora knowledge base'e yükler.
    Aynı içerik daha önce yüklendiyse 409 hatası fırlatır.
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

    # Duplicate kontrolü
    content_hash = _compute_hash(file_bytes)
    async with httpx.AsyncClient(timeout=30) as client:
        existing_hashes = await _get_existing_hashes(client)

    if content_hash[:16] in existing_hashes:
        raise DuplicateFileError(f"Bu dosya zaten yüklenmiş: {file.filename}")

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

    # Hash'i title'a kaydet — WeKnora description'ı otomatik eziyor, title güvenilir
    knowledge_id = data.get("data", {}).get("id")
    original_title = data.get("data", {}).get("title") or file.filename or ""
    if knowledge_id:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.put(
                    f"{WEKNORA_BASE_URL}/api/v1/knowledge/{knowledge_id}",
                    headers={**_weknora_headers(), "Content-Type": "application/json"},
                    json={"title": _embed_hash_in_title(original_title, content_hash)},
                )
        except Exception as e:
            logger.warning("Hash title kaydedilemedi: %s", e)

    logger.info(
        "WeKnora ingestion complete: file=%s kb_id=%s hash=%s",
        file.filename,
        WEKNORA_KB_ID,
        content_hash[:16],
    )

    return {
        "ok": True,
        "filename": file.filename,
        "kb_id": WEKNORA_KB_ID,
        "source": "weknora",
        "content_hash": content_hash,
        "weknora_response": data,
    }


async def _generate_image_description(
    image_bytes: bytes,
    mime_type: str,
    filename: str,
) -> str:
    """
    gpt-4o-mini ile görselin detaylı açıklamasını üretir.
    Bu açıklama WeKnora'ya text olarak kaydedilecek.
    """
    import base64
    from app.services.vision import call_openrouter_vision

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    messages = [
        {
            "role": "system",
            "content": (
                "Sen bir görsel analiz uzmanısın. "
                "Görseldeki her detayı kapsamlı şekilde açıkla. "
                "Nesneleri, renkleri, konumları, metinleri ve bağlamı detaylıca belirt. "
                "Açıklamanı Türkçe yaz."
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                },
                {
                    "type": "text",
                    "text": "Bu görseli tüm detaylarıyla açıkla. Görsel indeksleme için kullanılacak.",
                },
            ],
        },
    ]

    data = await call_openrouter_vision(messages)
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("Vision model yanıt vermedi")

    content = choices[0].get("message", {}).get("content", "")
    return content.strip()


async def ingest_image_to_weknora(
    image_bytes: bytes,
    mime_type: str,
    filename: str,
) -> dict:
    """
    Görseli LLM ile analiz eder, açıklamayı WeKnora'ya text olarak kaydeder.
    Aynı içerik daha önce yüklendiyse 409 hatası fırlatır.
    Reparse + enable tetiklenir — Qdrant'ta aranabilir hale gelir.
    """
    if not WEKNORA_API_KEY:
        raise RuntimeError("WEKNORA_API_KEY is missing in environment")
    if not WEKNORA_KB_ID:
        raise RuntimeError("WEKNORA_KB_ID is missing in environment")

    # Duplicate kontrolü
    content_hash = _compute_hash(image_bytes)
    async with httpx.AsyncClient(timeout=30) as client:
        existing_hashes = await _get_existing_hashes(client)

    if content_hash[:16] in existing_hashes:
        raise DuplicateFileError(f"Bu görsel zaten yüklenmiş: {filename}")

    # 1) Görsel açıklaması üret
    logger.info("Generating image description for: %s", filename)
    description = await _generate_image_description(image_bytes, mime_type, filename)

    if not description:
        raise RuntimeError("Görsel açıklaması üretilemedi")

    # 2) Açıklamayı WeKnora'ya text olarak yükle
    text_content = (
        f"[Görsel Dosyası: {filename}]\n\n"
        f"[Görsel Açıklaması]\n{description}"
    )

    upload_url = f"{WEKNORA_BASE_URL}/api/v1/knowledge-bases/{WEKNORA_KB_ID}/knowledge/manual"

    payload = {
        "title": _embed_hash_in_title(f"Görsel: {filename}", content_hash),
        "content": text_content,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                upload_url,
                headers={**_weknora_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise RuntimeError(
            f"WeKnora image ingestion error (status={e.response.status_code}): {detail}"
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"WeKnora unreachable: {e}")

    logger.info(
        "Image ingested to WeKnora: file=%s description_length=%d hash=%s",
        filename,
        len(description),
        content_hash[:16],
    )

    knowledge_id = data.get("data", {}).get("id")

    # 3) Reparse + enable tetikle, title'ı da güncelle
    if knowledge_id:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(
                    f"{WEKNORA_BASE_URL}/api/v1/knowledge/{knowledge_id}/reparse",
                    headers=_weknora_headers(),
                )
                await client.put(
                    f"{WEKNORA_BASE_URL}/api/v1/knowledge/{knowledge_id}",
                    headers={**_weknora_headers(), "Content-Type": "application/json"},
                    json={"enable_status": "enabled"},
                )
            logger.info("WeKnora reparse + enable triggered for knowledge_id=%s", knowledge_id)
        except Exception as e:
            logger.warning("WeKnora reparse/enable failed: %s", e)

    return {
        "ok": True,
        "filename": filename,
        "kb_id": WEKNORA_KB_ID,
        "source": "weknora_vision",
        "description_length": len(description),
        "content_hash": content_hash,
        **({"knowledge_id": knowledge_id} if knowledge_id else {}),
        "weknora_response": data,
    }


class DuplicateFileError(Exception):
    """Aynı içerik daha önce yüklendiğinde fırlatılır."""
    pass