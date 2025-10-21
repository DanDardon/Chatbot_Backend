#DB_USER = "ADMIN"
#DB_PASS = "Rd30072003!!"
#DB_DSN = "(description= (retry_count=20)(retry_delay=3)(address=(protocol=tcps)(port=1522)(host=adb.us-ashburn-1.oraclecloud.com))(connect_data=(service_name=geeb562edc24945_agentemedico_high.adb.oraclecloud.com))(security=(ssl_server_dn_match=yes)))"


import os
from pathlib import Path

DB_USER = os.getenv("DB_USER", "ADMIN")
DB_PASS = os.getenv("DB_PASS", "Rd30072003!!")
DB_DSN_ALIAS  = os.getenv("DB_DSN_ALIAS", "agentemedico_high")
DB_WALLET_DIR = os.getenv("DB_WALLET_DIR", r"C:\Users\dardo\Documents\OCTAVO SEMESTRE\DESAROLLO WEB\PROYECTOS\chatbot-farmacia\backend\wallet")
DB_WALLET_PASS = os.getenv("DB_WALLET_PASS", "Rd30072003!!")  # <-- si tu wallet pide passphrase, rellénala por variable de entorno

def validate_wallet_dir() -> Path:
    p = Path(DB_WALLET_DIR)
    if not p.exists():
        raise FileNotFoundError(f"DB_WALLET_DIR no existe: {p}")
    return p
