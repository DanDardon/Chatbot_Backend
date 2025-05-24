import cx_Oracle
from config import DB_USER, DB_PASS, DB_DSN

def get_connection():
    
    try:
        conn = cx_Oracle.connect(user=DB_USER, password=DB_PASS, dsn=DB_DSN)
        print("✅ Conexión exitosa a Oracle")
        return conn
    except cx_Oracle.DatabaseError as e:
        error, = e.args
        print("❌ Error al conectar con Oracle:", error.message)
        return None
        


if __name__ == "__main__":
    get_connection()
