import httpx
from app.core.config import settings

def main():
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENROUTER_MODEL_PRIMARY,
        "messages": [{"role": "user", "content": "Merhaba! 1 cümle ile kendini tanıt."}],
    }

    with httpx.Client(timeout=60) as client:
        r = client.post(url, headers=headers, json=payload)

    print("status:", r.status_code)
    print("body:", r.text)

if __name__ == "__main__":
    main()