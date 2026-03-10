import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import settings

router = APIRouter(prefix="/health", tags=["health"])

WEKNORA_HOST = getattr(settings, "WEKNORA_APP_HOST", "localhost")
WEKNORA_PORT = int(getattr(settings, "WEKNORA_APP_PORT", 8080))
WEKNORA_API_KEY = getattr(settings, "WEKNORA_API_KEY", None)
WEKNORA_KB_ID = getattr(settings, "WEKNORA_KB_ID", None)


@router.get("/weknora")
async def health_weknora():
    if not WEKNORA_API_KEY:
        raise HTTPException(status_code=500, detail="WEKNORA_API_KEY is missing")
    if not WEKNORA_KB_ID:
        raise HTTPException(status_code=500, detail="WEKNORA_KB_ID is missing")

    base = f"http://{WEKNORA_HOST}:{WEKNORA_PORT}"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # 1) Servis ayakta mı?
            r_health = await client.get(f"{base}/health")
            if r_health.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"WeKnora health check failed (status={r_health.status_code})",
                )

            # 2) API key + KB erişilebilir mi?
            headers = {"X-API-Key": WEKNORA_API_KEY}
            r_kb = await client.get(
                f"{base}/api/v1/knowledge-bases/{WEKNORA_KB_ID}",
                headers=headers,
            )
            if r_kb.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"WeKnora KB check failed (status={r_kb.status_code}): {r_kb.text}",
                )

            return {
                "status": "ok",
                "weknora": "reachable",
                "kb_id": WEKNORA_KB_ID,
                "auth": "ok",
            }

    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="WeKnora unreachable: timeout")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"WeKnora unreachable: {e}")