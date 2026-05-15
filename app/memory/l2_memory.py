"""
memory/l2_memory.py  —  DÜZELTİLMİŞ VERSİYON

Değişiklik:
  trigger_l2_update() artık db parametresi ALMAZ.
  L2 task'ı kendi SessionLocal() oturumunu açıp kapatır.
  Böylece FastAPI request session'ının kapanması L2'yi çökertmez.

chat.py'de güncelleme (tek satır):
    # ESKİ:
    trigger_l2_update(user_id=user_id, db=db)
    # YENİ:
    trigger_l2_update(user_id=user_id)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.db.postgres import SessionLocal  # ← kendi session'ını açmak için

logger = logging.getLogger(__name__)

# ── Debounce tablosu: {user_id: asyncio.Task} ─────────────────────────────────
_pending_tasks: dict[int, asyncio.Task] = {}

L2_DEBOUNCE_SECONDS: float = float(getattr(settings, "L2_DEBOUNCE_SECONDS", 15.0))
DEDUP_SIMILARITY_THRESHOLD: float = 0.92


# ── Qdrant semantic deduplication ─────────────────────────────────────────────

async def _embed_text(text: str) -> list[float] | None:
    api_key = getattr(settings, "OPENROUTER_API_KEY", None)
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": getattr(settings, "OPENROUTER_EMBEDDING_MODEL", "text-embedding-3-small"),
                    "input": [text],
                },
            )
            r.raise_for_status()
            return r.json()["data"][0]["embedding"]
    except Exception as e:
        logger.warning("L2 embed hatası: %s", e)
        return None


async def _is_duplicate_in_qdrant(text: str, user_id: int) -> bool:
    qdrant_host = getattr(settings, "QDRANT_HOST", "qdrant")
    qdrant_port = int(getattr(settings, "QDRANT_REST_PORT", 6333))
    collection = getattr(settings, "QDRANT_COLLECTION", "ai_engine_docs")

    vector = await _embed_text(text)
    if not vector:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"http://{qdrant_host}:{qdrant_port}/collections/{collection}/points/search",
                headers={"Content-Type": "application/json"},
                json={
                    "vector": vector,
                    "limit": 1,
                    "score_threshold": DEDUP_SIMILARITY_THRESHOLD,
                    "filter": {
                        "must": [
                            {"key": "user_id", "match": {"value": user_id}},
                            {"key": "memory_type", "match": {"value": "l2"}},
                        ]
                    },
                    "with_payload": False,
                },
            )
            if r.status_code == 200:
                return len(r.json().get("result", [])) > 0
    except Exception as e:
        logger.debug("Qdrant dedup kontrolü başarısız (devam ediliyor): %s", e)
    return False


async def _upsert_to_qdrant(text: str, user_id: int, point_id: str) -> None:
    qdrant_host = getattr(settings, "QDRANT_HOST", "qdrant")
    qdrant_port = int(getattr(settings, "QDRANT_REST_PORT", 6333))
    collection = getattr(settings, "QDRANT_COLLECTION", "ai_engine_docs")

    vector = await _embed_text(text)
    if not vector:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.put(
                f"http://{qdrant_host}:{qdrant_port}/collections/{collection}/points",
                headers={"Content-Type": "application/json"},
                json={
                    "points": [{
                        "id": point_id,
                        "vector": vector,
                        "payload": {
                            "text": text,
                            "user_id": user_id,
                            "memory_type": "l2",
                        },
                    }]
                },
            )
    except Exception as e:
        logger.warning("L2 Qdrant upsert başarısız: %s", e)


# ── LLM ile global profil güncelleme ──────────────────────────────────────────

async def _update_global_profile_with_llm(
    current_profile: dict[str, Any],
    new_l1_summaries: list[str],
    new_key_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    api_key = getattr(settings, "OPENROUTER_API_KEY", None)
    if not api_key:
        return current_profile

    profile_text = json.dumps(current_profile, ensure_ascii=False, indent=2) if current_profile else "{}"
    summaries_text = "\n\n".join(
        f"--- Konuşma Özeti ---\n{s}" for s in new_l1_summaries if s
    )
    facts_text = "\n".join(
        f"[{f.get('role', '?')}] {f.get('content', '')[:300]}"
        for f in new_key_facts[:20]
    )

    user_content = (
        f"## Mevcut Kullanıcı Profili\n{profile_text}\n\n"
        f"## Yeni Konuşma Özetleri\n{summaries_text}\n\n"
        f"## Önemli Bilgiler\n{facts_text}"
    )
    system_content = (
        "Sen bir kullanıcı hafıza yöneticisisin. "
        "Kullanıcının geçmiş konuşmalarından elde edilen verileri analiz ederek "
        "kapsamlı bir kullanıcı profili güncelle.\n\n"
        "Profil şu alanları içermeli:\n"
        "- interests: kullanıcının ilgi alanları (liste)\n"
        "- decisions: aldığı önemli kararlar (liste)\n"
        "- style: yanıt stili tercihleri (kısa metin)\n"
        "- last_topics: son konuşulan konular (liste, max 5)\n"
        "- technical_stack: kullandığı teknolojiler (liste)\n\n"
        "SADECE JSON objesi döndür, başka hiçbir şey yazma. "
        "Mevcut profili yeni bilgilerle zenginleştir, eski bilgileri silme."
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": getattr(settings, "OPENROUTER_MODEL_PRIMARY", "openai/gpt-4o-mini"),
                    "messages": [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 600,
                },
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw_clean = raw.replace("```json", "").replace("```", "").strip()
            new_profile = json.loads(raw_clean)
            new_profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            return new_profile
    except Exception as e:
        logger.warning("L2 LLM profil güncelleme başarısız: %s", e)
        return current_profile


# ── Ana L2 Güncelleme Fonksiyonu ──────────────────────────────────────────────

async def _run_l2_update(user_id: int) -> None:
    """
    Arka planda çalışan L2 iş akışı.
    KENDİ db session'ını açar ve kapatır — request session'ına bağlı değil.
    """
    from app.memory.models.chat_room_memory import ChatRoomMemory
    from app.models.user import User

    logger.info("L2 güncelleme başlatıldı: user_id=%d", user_id)

    # ← Kritik düzeltme: kendi session'ını aç
    db = SessionLocal()

    try:
        # 1. Pending L1 kayıtlarını topla
        pending_records = (
            db.query(ChatRoomMemory)
            .filter(
                ChatRoomMemory.user_id == user_id,
                ChatRoomMemory.l2_pending == True,  # noqa: E712
            )
            .all()
        )

        if not pending_records:
            logger.debug("L2: pending kayıt yok, user_id=%d", user_id)
            return

        # 2. Veri topla
        new_summaries: list[str] = []
        new_key_facts: list[dict[str, Any]] = []
        record_ids: list[int] = []

        for rec in pending_records:
            record_ids.append(rec.id)
            summary_text = ""
            if rec.summary and isinstance(rec.summary, dict):
                summary_text = rec.summary.get("text", "")
            if summary_text:
                new_summaries.append(summary_text)
            if rec.key_facts and isinstance(rec.key_facts, list):
                new_key_facts.extend(rec.key_facts)

        # 3. Semantic deduplication
        unique_summaries: list[str] = []
        for summary in new_summaries:
            if not await _is_duplicate_in_qdrant(summary, user_id):
                unique_summaries.append(summary)
                await _upsert_to_qdrant(summary, user_id, str(uuid.uuid4()))
            else:
                logger.debug("L2 dedup: benzer özet atlandı")

        # 4. Mevcut global profili al
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning("L2: user bulunamadı user_id=%d", user_id)
            return

        current_profile = user.global_memory or {}

        # 5. LLM ile profili güncelle
        if unique_summaries or new_key_facts:
            updated_profile = await _update_global_profile_with_llm(
                current_profile,
                unique_summaries,
                new_key_facts,
            )
        else:
            updated_profile = current_profile

        # 6. Kaydet
        user.global_memory = updated_profile
        user.l2_updated_at = datetime.now(timezone.utc)

        for rec_id in record_ids:
            rec = db.query(ChatRoomMemory).filter(ChatRoomMemory.id == rec_id).first()
            if rec:
                rec.l2_pending = False

        db.commit()
        logger.info(
            "L2 güncelleme tamamlandı: user_id=%d, %d özet işlendi",
            user_id,
            len(unique_summaries),
        )

    except Exception as e:
        logger.error("L2 güncelleme hatası: user_id=%d hata=%s", user_id, e)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()  # ← her zaman kapat
        _pending_tasks.pop(user_id, None)


async def _debounced_l2_update(user_id: int) -> None:
    """Debouncing: L2_DEBOUNCE_SECONDS bekleyip sonra güncelle."""
    await asyncio.sleep(L2_DEBOUNCE_SECONDS)
    await _run_l2_update(user_id)


# ── Public API ─────────────────────────────────────────────────────────────────

def trigger_l2_update(user_id: int) -> None:
    """
    L1 güncellemesinden sonra chat.py tarafından çağrılır.
    db parametresi YOKTUR — L2 kendi session'ını yönetir.

    chat.py'de kullanım:
        trigger_l2_update(user_id=user_id)   # db YOK
    """
    existing = _pending_tasks.get(user_id)
    if existing and not existing.done():
        existing.cancel()
        logger.debug("L2 debounce: önceki task iptal edildi user_id=%d", user_id)

    task = asyncio.ensure_future(_debounced_l2_update(user_id))
    _pending_tasks[user_id] = task
    logger.debug(
        "L2 debounce task başlatıldı: user_id=%d bekleme=%.1fs",
        user_id,
        L2_DEBOUNCE_SECONDS,
    )


def get_l2_context_string(db: Any, user_id: int) -> str:
    """
    chat.py'nin sistem promptuna ekleyeceği L2 bağlam metnini döndürür.
    Bu fonksiyon request db'sini kullanır — sadece okuma yaptığı için sorun yok.
    """
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.global_memory:
        return ""

    profile = user.global_memory
    if not isinstance(profile, dict):
        return ""

    parts: list[str] = []

    interests = profile.get("interests", [])
    if interests:
        parts.append("İlgi Alanları: " + ", ".join(interests[:5]))

    tech_stack = profile.get("technical_stack", [])
    if tech_stack:
        parts.append("Teknolojiler: " + ", ".join(tech_stack[:8]))

    decisions = profile.get("decisions", [])
    if decisions:
        parts.append("Önceki Kararlar:\n" + "\n".join(f"- {d}" for d in decisions[:5]))

    style = profile.get("style", "")
    if style:
        parts.append(f"Yanıt Stili: {style}")

    last_topics = profile.get("last_topics", [])
    if last_topics:
        parts.append("Son Konular: " + ", ".join(last_topics[:5]))

    if not parts:
        return ""

    return "\n".join(parts)