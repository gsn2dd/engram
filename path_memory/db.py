import os
import psycopg2

def get_conn():
    return psycopg2.connect(
        dbname=os.environ.get("DB_NAME", "pathmemoria"),
        user=os.environ.get("DB_USER", "pathuser"),
        password=os.environ.get("DB_PASS", "pathpass"),
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)),
    )
