from fastapi import FastAPI

from app.db.postgres import Base, engine
from app.models.conversation import Conversation  # noqa: F401
from app.models.message import Message  # noqa: F401
from app.models.user import User  # noqa: F401 — tablolar Base.metadata'ya kayıt olsun
from app.routers.user import router as users_router
from app.routers.conversation import router as conversation_router
from app.routers.messages import router as messages_router
from app.routers.chat import router as chat_router
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router


app = FastAPI(title="Multimodal AI Engine")


@app.on_event("startup")
def create_tables():
    """Postgres'te users, conversations, messages tabloları yoksa oluşturur."""
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    """API giriş noktası; sağlık ve dokümantasyon linkleri."""
    return {
        "message": "Multimodal AI Engine API",
        "health": "/health",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(users_router)
app.include_router(conversation_router)
app.include_router(messages_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(health_router)
