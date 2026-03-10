from app.core.config import settings

print("OPENROUTER_API_KEY:", "SET" if settings.OPENROUTER_API_KEY else "MISSING")
print("OPENROUTER_MODEL_PRIMARY:", settings.OPENROUTER_MODEL_PRIMARY)