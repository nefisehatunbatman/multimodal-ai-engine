from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import List

import httpx
from fastapi import UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)

QDRANT_HOST = getattr(settings, "QDRANT_HOST", "qdrant")
QDRANT_REST_PORT = int(getattr(settings, "QDRANT_REST_PORT", 6333))
QDRANT_COLLECTION = getattr(settings, "QDRANT_COLLECTION", "ai_engine_docs")

QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_REST_PORT}"

OPENROUTER_API_KEY = getattr(settings, "OPENROUTER_API_KEY", None)
EMBEDDING_MODEL = getattr(settings, "OPENROUTER_EMBEDDING_MODEL", "text-embedding-3-small")


def qdrant_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
    }


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    text = " ".join(text.split()).strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        start = max(end - overlap, 0)

    return chunks


async def extract_text_from_file(file: UploadFile) -> str:
    suffix = Path(file.filename or "").suffix.lower()
    file_bytes = await file.read()

    if not file_bytes:
        return ""

    if suffix == ".txt":
        return file_bytes.decode("utf-8", errors="ignore").strip()

    if suffix == ".pdf":
        try:
            import pypdf
            from io import BytesIO

            reader = pypdf.PdfReader(BytesIO(file_bytes))
            texts = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    texts.append(page_text.strip())
            return "\n".join(texts).strip()
        except Exception as e:
            logger.warning("PDF text extraction failed: %s", e)
            return ""

    if suffix == ".docx":
        try:
            from io import BytesIO
            from docx import Document

            doc = Document(BytesIO(file_bytes))
            texts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
            return "\n".join(texts).strip()
        except Exception as e:
            logger.warning("DOCX text extraction failed: %s", e)
            return ""

    return ""


async def embed_batch(client: httpx.AsyncClient, texts: List[str]) -> List[List[float]]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is missing in environment")

    if not texts:
        return []

    url = "https://openrouter.ai/api/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": EMBEDDING_MODEL,
        "input": texts,
    }

    resp = await client.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()

    data = resp.json()
    embeddings = data.get("data", [])

    vectors: List[List[float]] = []
    for item in embeddings:
        emb = item.get("embedding")
        if isinstance(emb, list):
            vectors.append(emb)

    return vectors


async def ensure_collection(client: httpx.AsyncClient, vector_size: int) -> None:
    get_url = f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}"
    resp = await client.get(get_url, headers=qdrant_headers())

    if resp.status_code == 200:
        return

    create_url = f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}"
    payload = {
        "vectors": {
            "size": vector_size,
            "distance": "Cosine",
        }
    }

    create_resp = await client.put(create_url, headers=qdrant_headers(), json=payload)
    create_resp.raise_for_status()


async def ingest_file(file: UploadFile) -> dict:
    text = await extract_text_from_file(file)
    if not text.strip():
        raise RuntimeError("Dosyadan metin çıkarılamadı")

    chunks = chunk_text(text)
    if not chunks:
        raise RuntimeError("Chunk oluşturulamadı")

    async with httpx.AsyncClient(timeout=120) as client:
        vectors = await embed_batch(client, chunks)
        if not vectors:
            raise RuntimeError("Embedding üretilemedi")

        await ensure_collection(client, len(vectors[0]))

        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point_id = str(uuid.uuid4())
            points.append(
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": {
                        "text": chunk,
                        "source_file": file.filename,
                        "chunk_index": idx,
                        "content_hash": hashlib.md5(chunk.encode("utf-8")).hexdigest(),
                    },
                }
            )

        upsert_url = f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points"
        payload = {
            "points": points,
        }

        resp = await client.put(upsert_url, headers=qdrant_headers(), json=payload)
        resp.raise_for_status()

    return {
        "ok": True,
        "filename": file.filename,
        "chunk_count": len(chunks),
        "collection": QDRANT_COLLECTION,
    }