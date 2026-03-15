from pathlib import Path
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.services.weknora_ingestion import (
    ingest_file_to_weknora,
    ingest_image_to_weknora,
    DuplicateFileError,
)

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

WEKNORA_BASE_URL = f"http://{settings.WEKNORA_APP_HOST}:{settings.WEKNORA_APP_PORT}"


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


@router.get("/", status_code=200)
async def list_documents(
    page: int = Query(default=1, ge=1, description="Sayfa numarası"),
    page_size: int = Query(default=20, ge=1, le=100, description="Sayfa başına belge sayısı"),
    current_user: User = Depends(get_current_user),
):
    """
    KB'deki belgeleri sayfalı olarak listeler.
    Frontend'de belge seçimi ve pagination için kullanılır.
    """
    if not settings.WEKNORA_API_KEY:
        raise HTTPException(status_code=500, detail="WEKNORA_API_KEY is missing")
    if not settings.WEKNORA_KB_ID:
        raise HTTPException(status_code=500, detail="WEKNORA_KB_ID is missing")

    url = (
        f"{WEKNORA_BASE_URL}/api/v1/knowledge-bases/{settings.WEKNORA_KB_ID}/knowledge"
        f"?page={page}&page_size={page_size}"
    )
    headers = {"X-API-Key": settings.WEKNORA_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="WeKnora unreachable: timeout")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Belge listesi alınamadı: {e}")

    items = data.get("data") or []
    total = data.get("total", 0)

    documents = [
        {
            "id": d["id"],
            "title": d.get("title", ""),
            "file_type": d.get("file_type", ""),
            "file_name": d.get("file_name", ""),
            "parse_status": d.get("parse_status", ""),
            "enable_status": d.get("enable_status", ""),
            "created_at": d.get("created_at", ""),
        }
        for d in items
    ]

    return {
        "documents": documents,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/ingest", status_code=200)
async def upload_and_ingest(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """PDF, TXT, DOCX dosyalarını WeKnora'ya yükler. Aynı dosya tekrar yüklenemez."""
    validate_file_extension(file.filename)
    try:
        result = await ingest_file_to_weknora(file)
    except DuplicateFileError as e:
        raise HTTPException(status_code=409, detail=str(e))
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
async def upload_and_ingest_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Görseli gpt-4o-mini ile analiz eder, açıklamayı WeKnora'ya kaydeder. Aynı görsel tekrar yüklenemez."""
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
    except DuplicateFileError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Image ingestion failed: {e}")
    return result