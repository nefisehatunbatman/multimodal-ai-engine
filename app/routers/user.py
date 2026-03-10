from fastapi import Depends,APIRouter,HTTPException,status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError#veri tabani kisitlamalari saglanmazsa hata firlatir.

from app.schemas.user import UserCreate,UserOut
from app.db.deps import get_db
from app.models.user import User

router = APIRouter(prefix="/users",tags=["users"])

@router.post("/",response_model=UserOut,status_code=status.HTTP_201_CREATED)
def create_user(payload:UserCreate,db:Session = Depends(get_db)):
    user = User(username = payload.username)
    db.add(user)
    try:
          db.commit()
    except IntegrityError:
         db.rollback()
         #unique username yakalandı
         raise HTTPException(
              status_code=status.HTTP_409_CONFLICT,
              detail="Username already exists"
         )
    db.refresh(user)
    return user
@router.get("/",response_model=list[UserOut])
def list_users(db:Session = Depends(get_db)):
     return db.query(User).order_by(User.id.asc()).all()
    
  


