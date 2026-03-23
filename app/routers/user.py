from fastapi import Depends, APIRouter, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from app.db.deps import get_db
from app.models.user import User
from app.core.security import hash_password, verify_password, get_current_user

router = APIRouter(tags=["users"])


class UserCreate(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class UpdateUsernamePayload(BaseModel):
    new_username: str


class UpdatePasswordPayload(BaseModel):
    current_password: str
    new_password: str


# ── Kayıt ──────────────────────────────────────────────────────────────────────
@router.post("/users/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    """Yeni kullanıcı oluşturur."""
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu kullanıcı adı zaten kullanımda",
        )
    db.refresh(user)
    return user


# ── Mevcut kullanıcı bilgisi ────────────────────────────────────────────────────
# NOT: /users/me rotaları /users/{id} gibi dinamik segment rotalardan ÖNCE
#      tanımlanmalıdır; aksi hâlde FastAPI "me" kelimesini id olarak parse eder
#      ve 404/422 döner. Bu nedenle prefix router yerine tam path kullanıyoruz.
@router.get("/users/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Giriş yapmış kullanıcının bilgilerini döndürür."""
    return current_user


# ── Kullanıcı adı güncelle ─────────────────────────────────────────────────────
@router.patch("/users/me/username", response_model=UserOut)
def update_username(
    payload: UpdateUsernamePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Giriş yapmış kullanıcının kullanıcı adını günceller."""
    if not payload.new_username or not payload.new_username.strip():
        raise HTTPException(status_code=422, detail="Kullanıcı adı boş olamaz")
    new_username = payload.new_username.strip()
    existing = db.query(User).filter(User.username == new_username).first()
    if existing and existing.id != current_user.id:
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kullanımda")
    current_user.username = new_username
    db.add(current_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kullanımda")
    db.refresh(current_user)
    return current_user


# ── Şifre güncelle ─────────────────────────────────────────────────────────────
@router.patch("/users/me/password", status_code=200)
def update_password(
    payload: UpdatePasswordPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Giriş yapmış kullanıcının şifresini günceller."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mevcut şifre yanlış")
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=422, detail="Yeni şifre en az 4 karakter olmalı")
    current_user.hashed_password = hash_password(payload.new_password)
    db.add(current_user)
    db.commit()
    return {"ok": True, "message": "Şifre güncellendi"}