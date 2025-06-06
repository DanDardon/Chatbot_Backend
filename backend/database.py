import oracledb
from backend.config import DB_USER, DB_PASS, DB_DSN

def get_connection():
    try:
        conn = oracledb.connect(
            user=DB_USER,
            password=DB_PASS,
            dsn=DB_DSN
        )
        print("✅ Conexión exitosa a Oracle")
        return conn
    except oracledb.Error as e:
        print("❌ Error al conectar con Oracle:", str(e))
        return None

if __name__ == "__main__":
    get_connection()
