import json
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


async def expand_query(question: str) -> str:
    """
    Kullanıcının sorusunu LLM ile semantik olarak genişletir.
    Örn: "toplam maliyet" → "toplam maliyet, toplam gider, toplam gelir, finansal özet"
    Bu sayede WeKnora'da daha iyi chunk eşleşmesi sağlanır.
    """
    if not settings.OPENROUTER_API_KEY:
        return question

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENROUTER_MODEL_PRIMARY or "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Kullanıcının sorusunu belge araması için genişlet. "
                    "Soruyla semantik olarak ilgili 3-5 alternatif terim veya ifade üret. "
                    "Sadece terimleri virgülle ayırarak yaz, başka hiçbir şey yazma."
                ),
            },
            {"role": "user", "content": question},
        ],
        "temperature": 0.0,
        "max_tokens": 100,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            expanded = data["choices"][0]["message"]["content"].strip()
            logger.info("Query expanded: '%s' → '%s, %s'", question, question, expanded)
            return f"{question}, {expanded}"
    except Exception as e:
        logger.warning("Query expansion failed, using original question: %s", e)
        return question  # hata olursa orijinal soruyu kullan


async def search_weknora(
    question: str,
    limit: int = 5,
    document_ids: list[str] | None = None,
) -> list[str]:
    """
    WeKnora hybrid-search endpoint'ini kullanarak
    soruya en alakalı chunk'ları döndürür.
    WeKnora içinde: Ollama embed → Qdrant hybrid search

    NOT: WeKnora hybrid-search GET metodunu kullanır ama
    body ister. httpx'te json= parametresi GET'te body göndermez,
    bu yüzden content= ile raw bytes olarak gönderiyoruz.
    """
    if not question.strip():
        return []
    if not WEKNORA_API_KEY or not WEKNORA_KB_ID:
        logger.error("WEKNORA_API_KEY veya WEKNORA_KB_ID eksik")
        return []

    search_url = f"{WEKNORA_BASE_URL}/api/v1/knowledge-bases/{WEKNORA_KB_ID}/hybrid-search"
    payload: dict = {
        "query_text": question.strip(),
        "match_count": limit,
        "disable_keywords_match": False,
        "disable_vector_match": False,
    }

    # Belge filtresi — sadece seçili belgelerde ara
    if document_ids:
        payload["knowledge_ids"] = document_ids
        logger.info("RAG search filtered to %d document(s)", len(document_ids))

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method="GET",
                url=search_url,
                headers=_weknora_headers(),
                content=json.dumps(payload).encode("utf-8"),
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


async def retrieve_context(
    question: str,
    document_ids: list[str] | None = None,
) -> str:
    """
    chat.py tarafından çağrılır. API imzası değişmiyor.
    Soruyu önce genişletir, sonra WeKnora'da arar.
    document_ids verilirse sadece o belgelerde arar.
    """
    # Soruyu semantik olarak genişlet
    expanded_question = await expand_query(question)

    contexts = await search_weknora(expanded_question, limit=5, document_ids=document_ids)

    if not contexts:
        logger.warning("RAG context tamamen boş! Soru: %s", (question or "")[:80])
        return ""

    formatted_contexts = [
        f"[Belge Parçası {i + 1}]\n{ctx}"
        for i, ctx in enumerate(contexts[:5])
    ]
    return "\n\n---\n\n".join(formatted_contexts).strip()