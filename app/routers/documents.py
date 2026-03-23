from pathlib import Path
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.deps import get_db
from app.models.user import User
from app.models.user_document import UserDocument
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Kullaniciya ait belgeleri listeler.
    Hangi knowledge_id'nin hangi kullaniciya ait oldugu kendi DB'mizde tutulur.
    WeKnora title alanina hic guvenilmez.
    """
    if not settings.WEKNORA_API_KEY:
        raise HTTPException(status_code=500, detail="WEKNORA_API_KEY is missing")
    if not settings.WEKNORA_KB_ID:
        raise HTTPException(status_code=500, detail="WEKNORA_KB_ID is missing")

    # 1) Kullaniciya ait knowledge_id'leri kendi DB'den al
    user_docs = (
        db.query(UserDocument)
        .filter(UserDocument.user_id == current_user.id)
        .all()
    )

    if not user_docs:
        return {"documents": [], "page": page, "page_size": page_size, "total": 0}

    # knowledge_id -> filename mapping
    kid_to_filename: dict[str, str] = {
        ud.knowledge_id: ud.filename or "" for ud in user_docs
    }
    user_knowledge_ids = set(kid_to_filename.keys())

    # 2) WeKnora'dan tum belgeleri cek, kullaniciya ait olanlari filtrele
    headers = {"X-API-Key": settings.WEKNORA_API_KEY}
    url_base = f"{WEKNORA_BASE_URL}/api/v1/knowledge-bases/{settings.WEKNORA_KB_ID}/knowledge"

    all_items = []
    fetch_page = 1
    fetch_page_size = 100

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            while True:
                r = await client.get(
                    f"{url_base}?page={fetch_page}&page_size={fetch_page_size}",
                    headers=headers,
                )
                r.raise_for_status()
                data = r.json()
                items = data.get("data") or []
                total = data.get("total", 0)

                for d in items:
                    kid = str(d.get("id", ""))
                    if kid in user_knowledge_ids:
                        # Gercek dosya adini kendi DB'den al, WeKnora title'ına bakma
                        d["_filename"] = kid_to_filename[kid]
                        all_items.append(d)

                if fetch_page * fetch_page_size >= total or not items:
                    break
                fetch_page += 1

    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="WeKnora unreachable: timeout")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Belge listesi alinamadi: {e}")

    # 3) Pagination
    total_filtered = len(all_items)
    start = (page - 1) * page_size
    paged = all_items[start: start + page_size]

    documents = [
        {
            "id": d["id"],
            "title": d.get("_filename") or d.get("title", ""),
            "file_type": d.get("file_type", ""),
            "file_name": d.get("_filename") or d.get("file_name", ""),
            "parse_status": d.get("parse_status", ""),
            "enable_status": d.get("enable_status", ""),
            "created_at": d.get("created_at", ""),
        }
        for d in paged
    ]

    return {
        "documents": documents,
        "page": page,
        "page_size": page_size,
        "total": total_filtered,
    }


@router.post("/ingest", status_code=200)
async def upload_and_ingest(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PDF, TXT, DOCX dosyalarini WeKnora'ya yukler. knowledge_id DB'ye kaydedilir."""
    validate_file_extension(file.filename)
    knowledge_id = None
    filename = file.filename or ""
    try:
        result = await ingest_file_to_weknora(file, user_id=current_user.id)
        knowledge_id = result["knowledge_id"]
    except DuplicateFileError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        msg = str(e)
        # WeKnora 409: dosya zaten var ama bizim DB'de kaydı olmayabilir
        if "status=409" in msg:
            import re, json as _json
            m = re.search(r'\{.*\}', msg, re.DOTALL)
            if m:
                try:
                    body = _json.loads(m.group())
                    knowledge_id = str(body.get("data", {}).get("id", ""))
                    filename = body.get("data", {}).get("file_name", "") or filename
                except Exception:
                    pass
            if not knowledge_id:
                raise HTTPException(status_code=409, detail="Bu dosya zaten yüklenmiş")
        else:
            raise HTTPException(status_code=500, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ingestion failed: {e}")

    # Kullanici - belge iliskisini DB'ye kaydet (yoksa)
    existing = db.query(UserDocument).filter(
        UserDocument.user_id == current_user.id,
        UserDocument.knowledge_id == knowledge_id,
    ).first()
    if not existing:
        db.add(UserDocument(
            user_id=current_user.id,
            knowledge_id=knowledge_id,
            filename=filename,
        ))
        db.commit()

    return {"ok": True, "filename": filename, "knowledge_id": knowledge_id}


@router.post("/ingest-image", status_code=200)
async def upload_and_ingest_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gorseli analiz eder, WeKnora'ya kaydeder. knowledge_id DB'ye kaydedilir."""
    suffix = validate_image_extension(file.filename)
    mime_type = ALLOWED_IMAGE_MIME_TYPES.get(suffix, "image/jpeg")
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Gorsel dosyasi bos")

    knowledge_id = None
    filename = file.filename or "image"
    try:
        result = await ingest_image_to_weknora(
            image_bytes=image_bytes,
            mime_type=mime_type,
            filename=filename,
            user_id=current_user.id,
        )
        knowledge_id = result["knowledge_id"]
    except DuplicateFileError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        msg = str(e)
        if "status=409" in msg:
            import re, json as _json
            m = re.search(r'\{.*\}', msg, re.DOTALL)
            if m:
                try:
                    body = _json.loads(m.group())
                    knowledge_id = str(body.get("data", {}).get("id", ""))
                    filename = body.get("data", {}).get("file_name", "") or filename
                except Exception:
                    pass
            if not knowledge_id:
                raise HTTPException(status_code=409, detail="Bu gorsel zaten yuklenmis")
        else:
            raise HTTPException(status_code=500, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Image ingestion failed: {e}")

    # Kullanici - belge iliskisini DB'ye kaydet (yoksa)
    existing = db.query(UserDocument).filter(
        UserDocument.user_id == current_user.id,
        UserDocument.knowledge_id == knowledge_id,
    ).first()
    if not existing:
        db.add(UserDocument(
            user_id=current_user.id,
            knowledge_id=knowledge_id,
            filename=filename,
        ))
        db.commit()

    return {"ok": True, "filename": filename, "knowledge_id": knowledge_id}