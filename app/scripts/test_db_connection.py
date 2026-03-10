from sqlalchemy import text
from app.db.postgres import engine

def main ():
    #engine.connect()-->kısa süreli baglanti acar
    with engine.connect() as conn:
        #text ham sql yazmak icin kullanilir
        result = conn.execute(text("SELECT 1"))
        value = result.scalar()

        print("db connection ok",value)

if __name__ == "__main__":
    main()        