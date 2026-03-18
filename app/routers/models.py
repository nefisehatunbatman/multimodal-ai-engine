from fastapi import APIRouter, Depends
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter(prefix="/models", tags=["models"])

MODEL_CATALOG = [
    {
        "category": "Ücretsiz Modeller",
        "models": [
            {
                "id": "meta-llama/llama-3.1-8b-instruct:free",
                "name": "Llama 3.1 8B",
                "provider": "Meta",
                "context_length": 131072,
                "description": "Meta'nın hafif ve hızlı açık kaynak modeli.",
            },
            {
                "id": "meta-llama/llama-3.2-3b-instruct:free",
                "name": "Llama 3.2 3B",
                "provider": "Meta",
                "context_length": 131072,
                "description": "Çok hafif, düşük kaynak tüketimi.",
            },
            {
                "id": "google/gemma-2-9b-it:free",
                "name": "Gemma 2 9B",
                "provider": "Google",
                "context_length": 8192,
                "description": "Google'ın açık kaynak modeli.",
            },
            {
                "id": "mistralai/mistral-7b-instruct:free",
                "name": "Mistral 7B",
                "provider": "Mistral AI",
                "context_length": 32768,
                "description": "Hızlı ve verimli Avrupa yapımı model.",
            },
        ],
    },
    {
        "category": "Ücretli - Ekonomik",
        "models": [
            {
                "id": "openai/gpt-4o-mini",
                "name": "GPT-4o Mini",
                "provider": "OpenAI",
                "context_length": 128000,
                "description": "Hızlı, ekonomik ve güvenilir. Genel amaçlı kullanım için ideal.",
            },
            {
                "id": "google/gemini-flash-1.5",
                "name": "Gemini 1.5 Flash",
                "provider": "Google",
                "context_length": 1000000,
                "description": "Çok geniş context penceresi, ekonomik fiyat.",
            },
            {
                "id": "google/gemini-2.0-flash-001",
                "name": "Gemini 2.0 Flash",
                "provider": "Google",
                "context_length": 1048576,
                "description": "Gemini 2.0 ailesinin hızlı ve ekonomik versiyonu.",
            },
            {
                "id": "anthropic/claude-haiku-4-5",
                "name": "Claude Haiku 4.5",
                "provider": "Anthropic",
                "context_length": 200000,
                "description": "Anthropic'in en hızlı ve ekonomik modeli.",
            },
            {
                "id": "mistralai/mistral-small-3.1-24b-instruct",
                "name": "Mistral Small 3.1",
                "provider": "Mistral AI",
                "context_length": 128000,
                "description": "Mistral'ın ekonomik ama yetenekli modeli.",
            },
        ],
    },
    {
        "category": "Ücretli - Güçlü",
        "models": [
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "provider": "OpenAI",
                "context_length": 128000,
                "description": "OpenAI'nin güçlü multimodal modeli.",
            },
            {
                "id": "anthropic/claude-sonnet-4.5",
                "name": "Claude Sonnet 4.5",
                "provider": "Anthropic",
                "context_length": 200000,
                "description": "Kod ve analiz görevlerinde üstün performans.",
            },
            {
                "id": "anthropic/claude-sonnet-4.6",
                "name": "Claude Sonnet 4.6",
                "provider": "Anthropic",
                "context_length": 200000,
                "description": "Anthropic'in en güncel ve güçlü modeli.",
            },
            {
                "id": "google/gemini-pro-1.5",
                "name": "Gemini 1.5 Pro",
                "provider": "Google",
                "context_length": 2000000,
                "description": "Devasa context penceresi, çok yönlü güçlü model.",
            },
            {
                "id": "openai/o3-mini",
                "name": "o3 Mini",
                "provider": "OpenAI",
                "context_length": 200000,
                "description": "Derin düşünme ve muhakeme gerektiren görevler için.",
            },
        ],
    },
    {
        "category": "Vision (Görsel Anlama)",
        "models": [
            {
                "id": "openai/gpt-4o-mini",
                "name": "GPT-4o Mini",
                "provider": "OpenAI",
                "context_length": 128000,
                "description": "Görsel ve metin kombinasyonu için ekonomik seçim.",
            },
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "provider": "OpenAI",
                "context_length": 128000,
                "description": "Görsel analiz için en güçlü seçenek.",
            },
            {
                "id": "google/gemini-flash-1.5",
                "name": "Gemini 1.5 Flash",
                "provider": "Google",
                "context_length": 1000000,
                "description": "Çok sayıda görsel işleme için ideal.",
            },
            {
                "id": "anthropic/claude-sonnet-4-5",
                "name": "Claude Sonnet 4.5",
                "provider": "Anthropic",
                "context_length": 200000,
                "description": "Görsel anlama ve detaylı analiz.",
            },
        ],
    },
]

TEMPERATURE_PRESETS = [
    {
        "label": "Deterministik",
        "value": 0.0,
        "description": "Her seferinde aynı cevap. Tutarlılık gerektiren görevler için.",
    },
    {
        "label": "Dengeli",
        "value": 0.2,
        "description": "Varsayılan ayar. Tutarlı ama doğal cevaplar.",
    },
    {
        "label": "Yaratıcı",
        "value": 0.7,
        "description": "Daha çeşitli ve yaratıcı cevaplar.",
    },
    {
        "label": "Maksimum Yaratıcı",
        "value": 1.5,
        "description": "En özgün ve beklenmedik cevaplar. Yaratıcı yazarlık için.",
    },
]


@router.get("/", status_code=200)
def list_models(current_user: User = Depends(get_current_user)):
    return {
        "categories": MODEL_CATALOG,
        "temperature_presets": TEMPERATURE_PRESETS,
    }