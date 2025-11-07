import psycopg2
import msvcrt
from utils import get_connection


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
