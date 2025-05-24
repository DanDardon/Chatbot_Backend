import oracledb
from backend.config import DB_USER, DB_PASS, DB_DSN

# Fuerza modo THIN explícitamente
oracledb.init_oracle_client(lib_dir=None)  # <-- se asegura de no buscar Oracle Client

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
