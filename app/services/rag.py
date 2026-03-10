import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

WEKNORA_HOST = getattr(settings, "WEKNORA_APP_HOST", "localhost")
WEKNORA_PORT = int(getattr(settings, "WEKNORA_APP_PORT", 8080))
WEKNORA_API_KEY = getattr(settings, "WEKNORA_API_KEY", None)
WEKNORA_KB_ID = getattr(settings, "WEKNORA_KB_ID", None)

WEKNORA_BASE_URL = f"http://{WEKNORA_HOST}:{WEKNORA_PORT}"


def _weknora_headers() -> dict[str, str]:
    return {
        "X-API-Key": WEKNORA_API_KEY or "",
        "Content-Type": "application/json",
    }


def _clean_text(text: str) -> str:
    return " ".join(text.split()).strip()


async def search_weknora(question: str, limit: int = 5) -> list[str]:
    """
    WeKnora hybrid-search endpoint'ini kullanarak
    soruya en alakalı chunk'ları döndürür.
    WeKnora içinde: Ollama embed → Qdrant hybrid search
    """
    if not question.strip():
        return []
    if not WEKNORA_API_KEY or not WEKNORA_KB_ID:
        logger.error("WEKNORA_API_KEY veya WEKNORA_KB_ID eksik")
        return []

    search_url = f"{WEKNORA_BASE_URL}/api/v1/knowledge-bases/{WEKNORA_KB_ID}/hybrid-search"
    payload = {
        "query_text": question.strip(),
        "match_count": limit,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method="GET",
                url=search_url,
                headers=_weknora_headers(),
                json=payload,
            )
    except httpx.HTTPError as e:
        logger.warning("WeKnora search request failed: %s", e)
        return []

    if resp.status_code != 200:
        logger.warning(
            "WeKnora search failed: status=%s body=%s",
            resp.status_code,
            (resp.text or "")[:500],
        )
        return []

    data = resp.json()
    items = data.get("data") or []

    texts: list[str] = []
    seen: set[str] = set()

    for item in items:
        # summary chunk'larını atla, sadece text chunk'larını al
        if item.get("chunk_type") == "summary":
            continue
        text = item.get("content") or item.get("matched_content") or ""
        if isinstance(text, str):
            cleaned = _clean_text(text)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                texts.append(cleaned)

    logger.info("WeKnora search returned %d context chunks", len(texts))
    return texts


async def retrieve_context(question: str) -> str:
    """
    chat.py tarafından çağrılır. API imzası değişmiyor.
    """
    contexts = await search_weknora(question, limit=5)

    if not contexts:
        logger.warning("RAG context tamamen boş! Soru: %s", (question or "")[:80])
        return ""

    formatted_contexts = [
        f"[Belge Parçası {i + 1}]\n{ctx}"
        for i, ctx in enumerate(contexts[:5])
    ]
    return "\n\n---\n\n".join(formatted_contexts).strip()