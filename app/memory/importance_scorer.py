"""
memory/importance_scorer.py

Gelen mesaj veya metin parçalarının "önem derecesi"ni hesaplar.
Soru, karar, aksiyon, teknik terim ve kişisel bilgi ifadelerini tespit ederek
sadece stratejik önemi olan bilgilerin hafızaya aktarılmasını sağlar.

Kullanım:
    scorer = ImportanceScorer()
    score = scorer.score(text)          # 0.0–1.0
    facts = scorer.extract_key_facts(messages)  # önemli satırlar
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── Kural tabanlı anahtar kelime setleri ──────────────────────────────────────

# Türkçe + İngilizce soru kalıpları
_QUESTION_PATTERNS = re.compile(
    r"\b(nasıl|neden|ne zaman|nerede|kim|hangi|kaç|ne kadar|"
    r"how|why|when|where|who|which|what|how many|how much)\b"
    r"|[?？]",
    re.IGNORECASE,
)

# Karar / tercih ifadeleri
_DECISION_PATTERNS = re.compile(
    r"\b(karar verdim|tercih ettim|seçtim|kullanacağım|kullanıyorum|"
    r"decided|chose|will use|going to use|prefer|selected|picked)\b",
    re.IGNORECASE,
)

# Aksiyon / yapılacak iş ifadeleri
_ACTION_PATTERNS = re.compile(
    r"\b(yapılacak|gerekiyor|lazım|implement|todo|fix|refactor|"
    r"create|add|remove|update|deploy|migrate|integrate|"
    r"ekle|kaldır|güncelle|düzelt|taşı|entegre et)\b",
    re.IGNORECASE,
)

# Teknik anahtar terimler (hafızaya değer)
_TECHNICAL_PATTERNS = re.compile(
    r"\b(api|endpoint|model|schema|database|db|table|index|"
    r"cache|redis|kafka|postgres|postgresql|qdrant|vector|"
    r"token|jwt|auth|permission|role|"
    r"docker|kubernetes|aws|ec2|"
    r"python|fastapi|react|go|typescript)\b",
    re.IGNORECASE,
)

# ── YENİ: Kişisel bilgi ifadeleri ────────────────────────────────────────────
# Kullanıcının adı, yaşı, mesleği, yaşadığı yer gibi kişisel verileri yakalar
_PERSONAL_PATTERNS = re.compile(
    r"\b(adım|ismim|benim adım|bana .* de|beni .* olarak|"
    r"yaşındayım|yaşımdayım|yaşında|"
    r"çalışıyorum|çalışıyorum|mesleğim|işim|"
    r"okuyorum|öğrenciyim|mezunum|bölümüm|"
    r"oturuyorum|yaşıyorum|şehrinde|şehirdeyim|"
    r"doğdum|doğumluyum|"
    r"seviyorum|ilgileniyorum|hobim|"
    r"my name|i am|i'm|call me|"
    r"i work|i study|i live|i was born|"
    r"i like|i love|my hobby|my job|my major)\b",
    re.IGNORECASE,
)

# Önemsiz / boş gürültü ifadeleri (bunlar puanı düşürür)
_NOISE_PATTERNS = re.compile(
    r"^(tamam|ok|evet|hayır|teşekkür|merhaba|selam|"
    r"yes|no|ok|sure|thanks|hi|hello|bye|görüşürüz)\s*[.!]?\s*$",
    re.IGNORECASE,
)

# Ağırlık katsayıları
_W_QUESTION = 0.30
_W_DECISION = 0.40
_W_ACTION = 0.35
_W_TECHNICAL = 0.20
_W_PERSONAL = 0.40      # ← kişisel bilgiler yüksek öncelikli
_W_LENGTH_BONUS = 0.15
_NOISE_PENALTY = -0.50


@dataclass
class ScoredMessage:
    role: str
    content: str
    score: float
    tags: list[str]


class ImportanceScorer:
    """
    Kural tabanlı önem puanlayıcı.
    0.0 = tamamen önemsiz, 1.0 = çok kritik.

    threshold: Bu değerin üzerindeki mesajlar key_facts'e eklenir (varsayılan 0.35).
    """

    def __init__(self, threshold: float = 0.35):
        self.threshold = threshold

    def score(self, text: str) -> tuple[float, list[str]]:
        """
        Metni puanlar.
        Returns:
            (score: float 0.0–1.0, tags: list[str])
        """
        if not text or not text.strip():
            return 0.0, []

        text_stripped = text.strip()
        tags: list[str] = []
        raw_score = 0.0

        # Gürültü kontrolü
        if _NOISE_PATTERNS.match(text_stripped):
            return max(0.0, _NOISE_PENALTY + 0.5), ["noise"]

        # Kişisel bilgi tespiti — isim, yaş, meslek vb.
        if _PERSONAL_PATTERNS.search(text_stripped):
            raw_score += _W_PERSONAL
            tags.append("personal")

        # Soru tespiti
        if _QUESTION_PATTERNS.search(text_stripped):
            raw_score += _W_QUESTION
            tags.append("question")

        # Karar tespiti
        if _DECISION_PATTERNS.search(text_stripped):
            raw_score += _W_DECISION
            tags.append("decision")

        # Aksiyon tespiti
        if _ACTION_PATTERNS.search(text_stripped):
            raw_score += _W_ACTION
            tags.append("action")

        # Teknik terim tespiti
        tech_matches = len(_TECHNICAL_PATTERNS.findall(text_stripped))
        if tech_matches > 0:
            raw_score += min(_W_TECHNICAL * tech_matches, _W_TECHNICAL * 3)
            tags.append("technical")

        # Uzunluk bonusu (200 karakter üzeri)
        if len(text_stripped) > 200:
            raw_score += _W_LENGTH_BONUS
            tags.append("long")

        final_score = min(round(raw_score, 3), 1.0)
        return final_score, tags

    def extract_key_facts(
        self,
        messages: list[dict[str, Any]],
        max_facts: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Mesaj listesinden önem eşiği üzerindeki mesajları çıkarır.
        Sistem mesajları dahil edilmez.

        Returns:
            [{"role": ..., "content": ..., "score": ..., "tags": [...]}, ...]
        """
        scored: list[ScoredMessage] = []

        for msg in messages:
            role = msg.get("role", "user")

            # Sistem promptlarını key_facts'e alma — karışıklık yaratır
            if role == "system":
                continue

            content = msg.get("content", "")

            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                content = " ".join(text_parts)

            content_str = str(content).strip()
            if not content_str:
                continue

            sc, tags = self.score(content_str)
            if sc >= self.threshold:
                scored.append(ScoredMessage(
                    role=role,
                    content=content_str,
                    score=sc,
                    tags=tags,
                ))

        # Puana göre sırala, en önemlileri al
        scored.sort(key=lambda x: x.score, reverse=True)
        top = scored[:max_facts]

        return [
            {
                "role": s.role,
                "content": s.content[:500],
                "score": s.score,
                "tags": s.tags,
            }
            for s in top
        ]

    def filter_important(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Eşik üzerindeki mesajları orijinal sırayla döndürür.
        Sistem mesajları her zaman dışlanır.
        """
        result = []
        for msg in messages:
            # Sistem promptlarını dışla
            if msg.get("role") == "system":
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict)
                )
            sc, _ = self.score(str(content))
            if sc >= self.threshold:
                result.append(msg)
        return result