"""
memory/l1_memory.py

L1 Yerel Hafıza Katmanı — Chat Room Memory

Token tabanlı tetikleme:
- Konuşma toplam token sayısı L1_TRIGGER_TOKENS eşiğine ulaşınca ilk özet üretilir.
- Her L1_INCREMENT_TOKENS token artışında özet inkremental olarak güncellenir.
- Özet PostgreSQL chat_room_memory tablosuna JSONB olarak yazılır.
- Her L1 güncellemesi sonrasında L2 worker'ı tetikler (l2_pending=True).

Düzeltme:
- Sistem mesajları (role="system") artık özet ve key_facts'e dahil edilmiyor.
- filter_important kaldırıldı: tüm user/assistant mesajları LLM'e gönderiliyor.
  Bu sayede adı, yaşı, kitap gibi kişisel bilgiler özete giriyor.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.memory.importance_scorer import ImportanceScorer

logger = logging.getLogger(__name__)

# ── Eşik değerleri ────────────────────────────────────────────────────────────
L1_TRIGGER_TOKENS: int = int(getattr(settings, "L1_TRIGGER_TOKENS", 2000))
L1_INCREMENT_TOKENS: int = int(getattr(settings, "L1_INCREMENT_TOKENS", 1000))

_scorer = ImportanceScorer(threshold=0.35)


# ── Sistem mesajı filtresi ─────────────────────────────────────────────────────

def _exclude_system(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sistem promptlarını mesaj listesinden çıkarır."""
    return [m for m in messages if m.get("role") != "system"]


# ── OpenRouter yardımcısı ──────────────────────────────────────────────────────

async def _call_llm_for_summary(
    messages_for_summary: list[dict[str, Any]],
    previous_summary: str,
) -> str:
    """
    OpenRouter üzerinden mevcut özeti yeni mesajlarla güncelleyerek
    inkremental özet üretir.
    Sistem mesajları özete dahil edilmez.
    filter_important kaldırıldı — tüm user/assistant mesajları gönderiliyor.
    """
    if not getattr(settings, "OPENROUTER_API_KEY", None):
        logger.warning("OPENROUTER_API_KEY eksik, L1 özet üretilemiyor")
        return previous_summary

    # Sistem mesajlarını dışla
    user_assistant_msgs = _exclude_system(messages_for_summary)

    # Hiç mesaj yoksa ve önceki özet de yoksa boş dön
    if not user_assistant_msgs and not previous_summary:
        return ""

    # Tüm user/assistant mesajlarını LLM'e gönder (filtre yok)
    messages_text = "\n".join(
        f"[{m['role'].upper()}]: {str(m.get('content', ''))[:400]}"
        for m in user_assistant_msgs[-30:]
    )

    system_content = (
        "Sen bir konuşma hafıza yöneticisisin. "
        "Verilen konuşma mesajlarını ve mevcut özeti analiz ederek "
        "güncellenmiş, sıkıştırılmış bir özet üret. "
        "Özellikle şunları yakala: kullanıcı kararları, teknik tercihler, "
        "yapılacaklar listesi, önemli sorular ve cevaplar, "
        "kullanıcının adı ve kişisel bilgileri (varsa). "
        "Özet Türkçe olsun, maksimum 300 kelime. "
        "Yalnızca özet metnini yaz, başka hiçbir şey ekleme."
    )

    user_content = ""
    if previous_summary:
        user_content += f"## Mevcut Özet\n{previous_summary}\n\n"
    if messages_text:
        user_content += f"## Yeni Mesajlar\n{messages_text}"

    payload = {
        "model": getattr(settings, "OPENROUTER_MODEL_PRIMARY", "openai/gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": 500,
    }

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning("L1 LLM özet başarısız: %s", e)
        return previous_summary


# ── Ana L1 Yöneticisi ──────────────────────────────────────────────────────────

class L1MemoryManager:
    """
    PostgreSQL üzerinde L1 hafızayı yönetir.

    Args:
        db: SQLAlchemy Session (sync — FastAPI dependency)
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_record(self, conversation_id: int):
        from app.memory.models.chat_room_memory import ChatRoomMemory
        return (
            self.db.query(ChatRoomMemory)
            .filter(ChatRoomMemory.conversation_id == conversation_id)
            .first()
        )

    def _create_or_get(self, conversation_id: int, user_id: int):
        from app.memory.models.chat_room_memory import ChatRoomMemory
        record = self._get_record(conversation_id)
        if record is None:
            record = ChatRoomMemory(
                conversation_id=conversation_id,
                user_id=user_id,
                summary=None,
                key_facts=[],
                total_tokens=0,
                last_summary_at_tokens=0,
                summary_version=0,
                l2_pending=False,
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
        return record

    def update_token_count(
        self,
        conversation_id: int,
        user_id: int,
        new_total_tokens: int,
    ) -> None:
        record = self._create_or_get(conversation_id, user_id)
        record.total_tokens = new_total_tokens
        self.db.commit()

    def needs_update(self, conversation_id: int, user_id: int, current_tokens: int) -> bool:
        record = self._get_record(conversation_id)

        if record is None or record.summary_version == 0:
            return current_tokens >= L1_TRIGGER_TOKENS

        tokens_since_last = current_tokens - record.last_summary_at_tokens
        return tokens_since_last >= L1_INCREMENT_TOKENS

    async def maybe_update(
        self,
        conversation_id: int,
        user_id: int,
        messages: list[dict[str, Any]],
        current_total_tokens: int,
    ) -> bool:
        """
        Token eşiği aşıldıysa özeti günceller.
        Sistem mesajları özete ve key_facts'e dahil edilmez.

        Returns:
            True → özet güncellendi, False → güncelleme gerekmedi
        """
        record = self._create_or_get(conversation_id, user_id)
        record.total_tokens = current_total_tokens

        if not self.needs_update(conversation_id, user_id, current_total_tokens):
            self.db.commit()
            return False

        logger.info(
            "L1 özet tetiklendi: conversation_id=%d tokens=%d version=%d",
            conversation_id,
            current_total_tokens,
            record.summary_version,
        )

        # Mevcut özeti al
        previous_summary = ""
        if record.summary and isinstance(record.summary, dict):
            previous_summary = record.summary.get("text", "")

        # Sistem mesajlarını dışla, key_facts üret
        user_assistant_msgs = _exclude_system(messages)
        key_facts = _scorer.extract_key_facts(user_assistant_msgs, max_facts=15)

        # LLM ile özet güncelle
        new_summary_text = await _call_llm_for_summary(messages, previous_summary)

        # Kayıt güncelle
        record.summary = {
            "text": new_summary_text,
            "generated_at_tokens": current_total_tokens,
        }
        record.key_facts = key_facts
        record.last_summary_at_tokens = current_total_tokens
        record.summary_version = (record.summary_version or 0) + 1
        record.l2_pending = True

        self.db.commit()

        logger.info(
            "L1 özet güncellendi: conversation_id=%d version=%d",
            conversation_id,
            record.summary_version,
        )
        return True

    def get_context_string(self, conversation_id: int) -> str:
        """
        chat.py'nin sistem promptuna ekleyeceği L1 bağlam metnini döndürür.
        """
        record = self._get_record(conversation_id)
        if not record or not record.summary:
            return ""

        summary_text = ""
        if isinstance(record.summary, dict):
            summary_text = record.summary.get("text", "")
        elif isinstance(record.summary, str):
            summary_text = record.summary

        facts_text = ""
        if record.key_facts and isinstance(record.key_facts, list):
            fact_lines = [
                f"- [{f.get('role', '?').upper()}] {f.get('content', '')[:200]}"
                for f in record.key_facts[:10]
            ]
            facts_text = "\n".join(fact_lines)

        parts = []
        if summary_text.strip():
            parts.append(f"**Konuşma Özeti:**\n{summary_text.strip()}")
        if facts_text.strip():
            parts.append(f"**Önemli Noktalar:**\n{facts_text.strip()}")

        return "\n\n".join(parts)

    def get_stats(self, conversation_id: int) -> dict[str, Any]:
        """Debug / monitoring için istatistik döner."""
        record = self._get_record(conversation_id)
        if not record:
            return {"exists": False}
        return {
            "exists": True,
            "total_tokens": record.total_tokens,
            "last_summary_at_tokens": record.last_summary_at_tokens,
            "summary_version": record.summary_version,
            "l2_pending": record.l2_pending,
            "key_facts_count": len(record.key_facts or []),
        }