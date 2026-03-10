from pydantic import BaseModel ,Field

class UserCreate(BaseModel):
    username : str = Field(min_length=3, max_length=50)

#kullaniciya gösterilicek olan 
class UserOut(BaseModel):
    id: int
    username: str
#benim elimde orm nesnesi var pydantic dictionary okur bu ayar orm nesnesini okuyabilmesi icin yapilir
    class Config:
      from_attributes = True