from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.weknora_ingestion import ingest_file_to_weknora, ingest_image_to_weknora

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = (".txt", ".pdf", ".docx")

ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

ALLOWED_IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def validate_file_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenen formatlar: {', '.join(ALLOWED_EXTENSIONS)}. Gelen: {suffix or 'unknown'}",
        )
    return suffix


def validate_image_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenen formatlar: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}. Gelen: {suffix or 'unknown'}",
        )
    return suffix


@router.post("/ingest", status_code=200)
async def upload_and_ingest(file: UploadFile = File(...)):
    """PDF, TXT, DOCX dosyalarını WeKnora'ya yükler."""
    validate_file_extension(file.filename)

    try:
        result = await ingest_file_to_weknora(file)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Ingestion error: {e.response.text or str(e)}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ingestion failed: {e}")

    return result


@router.post("/ingest-image", status_code=200)
async def upload_and_ingest_image(file: UploadFile = File(...)):
    """
    Görseli gpt-4o-mini ile analiz eder, açıklamayı WeKnora'ya kaydeder.
    Görsel içeriği Qdrant'ta aranabilir hale gelir.
    """
    suffix = validate_image_extension(file.filename)
    mime_type = ALLOWED_IMAGE_MIME_TYPES.get(suffix, "image/jpeg")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Görsel dosyası boş")

    try:
        result = await ingest_image_to_weknora(
            image_bytes=image_bytes,
            mime_type=mime_type,
            filename=file.filename or "image",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Image ingestion failed: {e}")

    return result