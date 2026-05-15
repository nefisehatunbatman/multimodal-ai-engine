"""
memory/token_budget.py

Bağlam penceresinde sistem promptu, L1 hafıza, L2 hafıza ve yeni mesajlar için
hassas token bütçesi hesaplar.

Kullanım:
    budget = TokenBudget(context_limit=8192)
    allocation = budget.allocate(
        system_prompt=system_text,
        l1_summary=l1_text,
        l2_memory=l2_text,
        history_messages=messages,
        new_user_message=user_msg,
    )
    # allocation.history_messages → bütçeye sığan kırpılmış geçmiş
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Basit token tahmincisi ─────────────────────────────────────────────────────
# tiktoken bağımlılığı olmaksızın: ortalama 4 karakter ≈ 1 token (İngilizce/Türkçe karışık)
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    """Metin uzunluğundan token sayısı tahmin eder."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, list):
            # vision mesajları: her item'ın text alanını topla
            for item in content:
                if isinstance(item, dict):
                    total += _estimate_tokens(item.get("text", ""))
        else:
            total += _estimate_tokens(str(content))
        total += 4  # role + overhead
    return total


# ── Sabit bütçe oranları ───────────────────────────────────────────────────────
SYSTEM_BUDGET_RATIO = 0.10       # Bağlam penceresinin %10'u sistem promptuna
L1_BUDGET_RATIO = 0.10           # %10 → L1 yerel özet
L2_BUDGET_RATIO = 0.08           # %8  → L2 global profil
NEW_MESSAGE_BUDGET_RATIO = 0.12  # %12 → yeni kullanıcı mesajı + yanıt rezervi
HISTORY_BUDGET_RATIO = 0.60      # %60 → geçmiş mesajlar (kırpılabilir)

# Minimum garantiler (token)
MIN_HISTORY_TOKENS = 200
MIN_NEW_MESSAGE_TOKENS = 100


@dataclass
class BudgetAllocation:
    """allocate() çıktısı."""
    context_limit: int

    system_tokens_used: int = 0
    l1_tokens_used: int = 0
    l2_tokens_used: int = 0
    new_message_tokens_used: int = 0
    history_tokens_used: int = 0

    # Kırpılmış geçmiş mesaj listesi (en yeniden en eskiye doğru kırpılır)
    history_messages: list[dict[str, Any]] = field(default_factory=list)

    # Kırpma gerçekleştiyse True
    history_was_truncated: bool = False

    @property
    def total_used(self) -> int:
        return (
            self.system_tokens_used
            + self.l1_tokens_used
            + self.l2_tokens_used
            + self.new_message_tokens_used
            + self.history_tokens_used
        )

    @property
    def remaining(self) -> int:
        return self.context_limit - self.total_used


class TokenBudget:
    """
    Bağlam penceresi token bütçeleyici.

    Args:
        context_limit: Modelin toplam token limiti (varsayılan: 8192)
        reserve_for_output: Modelin yanıt üretmesi için rezerv (varsayılan: 1024)
    """

    def __init__(self, context_limit: int = 8192, reserve_for_output: int = 1024):
        self.context_limit = context_limit
        # Giriş için kullanılabilir toplam
        self.input_limit = context_limit - reserve_for_output

    def allocate(
        self,
        system_prompt: str = "",
        l1_summary: str = "",
        l2_memory: str = "",
        history_messages: list[dict[str, Any]] | None = None,
        new_user_message: str = "",
    ) -> BudgetAllocation:
        """
        Tüm bileşenler için token bütçesi hesaplar.
        Geçmiş mesajlar gerekirse en eski mesajlardan kırpılır.
        """
        history_messages = history_messages or []
        alloc = BudgetAllocation(context_limit=self.input_limit)

        # 1. Sabit bileşenler (kırpılamaz)
        alloc.system_tokens_used = min(
            _estimate_tokens(system_prompt),
            int(self.input_limit * SYSTEM_BUDGET_RATIO),
        )
        alloc.l1_tokens_used = min(
            _estimate_tokens(l1_summary),
            int(self.input_limit * L1_BUDGET_RATIO),
        )
        alloc.l2_tokens_used = min(
            _estimate_tokens(l2_memory),
            int(self.input_limit * L2_BUDGET_RATIO),
        )
        alloc.new_message_tokens_used = max(
            _estimate_tokens(new_user_message),
            MIN_NEW_MESSAGE_TOKENS,
        )

        # 2. Geçmiş için kalan bütçe
        fixed_used = (
            alloc.system_tokens_used
            + alloc.l1_tokens_used
            + alloc.l2_tokens_used
            + alloc.new_message_tokens_used
        )
        history_budget = max(self.input_limit - fixed_used, MIN_HISTORY_TOKENS)

        # 3. Geçmişi kırp (en yeniler öncelikli — eski mesajlar atılır)
        kept_messages: list[dict[str, Any]] = []
        running_tokens = 0
        truncated = False

        for msg in reversed(history_messages):
            msg_tokens = _estimate_messages_tokens([msg])
            if running_tokens + msg_tokens <= history_budget:
                kept_messages.append(msg)
                running_tokens += msg_tokens
            else:
                truncated = True
                break

        kept_messages.reverse()  # kronolojik sıraya geri al

        alloc.history_messages = kept_messages
        alloc.history_tokens_used = running_tokens
        alloc.history_was_truncated = truncated

        if truncated:
            dropped = len(history_messages) - len(kept_messages)
            logger.info(
                "Token budget: %d/%d kullanıldı, %d eski mesaj kırpıldı",
                alloc.total_used,
                self.input_limit,
                dropped,
            )

        return alloc

    def format_context_block(
        self,
        l1_summary: str,
        l2_memory: str,
    ) -> str:
        """
        L1 + L2 verilerini sistem promptuna eklenecek
        tek bir bağlam bloğuna dönüştürür.
        """
        parts: list[str] = []

        if l1_summary.strip():
            parts.append(
                "## Konuşma Özeti (L1 Kısa Vadeli Hafıza)\n"
                f"{l1_summary.strip()}"
            )

        if l2_memory.strip():
            parts.append(
                "## Kullanıcı Profili (L2 Uzun Vadeli Hafıza)\n"
                f"{l2_memory.strip()}"
            )

        if not parts:
            return ""

        return (
            "---\n"
            + "\n\n".join(parts)
            + "\n---"
        )