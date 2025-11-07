import psycopg2
import msvcrt


DB_CONFIG = {
    "dbname": "citadel_db",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def read_qr_code():
    qr_data = ""
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            break
        qr_data += ch
    return qr_data.strip()


def verify_qr_in_db(qr_value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT fullname FROM students WHERE student_no = %s", (qr_value,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        return True, row[0]
    return False, None
