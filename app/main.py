from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.postgres import Base, engine
from app.models.conversation import Conversation  # noqa: F401
from app.models.message import Message  # noqa: F401
from app.models.user import User  # noqa: F401
from app.routers.user import router as users_router
from app.routers.auth import router as auth_router
from app.routers.conversation import router as conversation_router
from app.routers.messages import router as messages_router
from app.routers.chat import router as chat_router
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router
from app.routers.models import router as models_router

app = FastAPI(
    title="Multimodal AI Engine",
    description="RAG, Vision & Real-Time Messaging API. JWT ile kimlik doğrulama gerektirir.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def create_tables():
    """Postgres'te tablolar yoksa oluşturur."""
    Base.metadata.create_all(bind=engine)


@app.get("/", tags=["root"])
def root():
    return {
        "message": "Multimodal AI Engine API",
        "health": "/health",
        "docs": "/docs",
        "redoc": "/redoc",
    }


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(conversation_router)
app.include_router(messages_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(health_router)
app.include_router(models_router)