import psycopg2, msvcrt
from db_utils import get_connection


def read_qr_code():
    qr_data = ""
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            break
        qr_data += ch
    return qr_data.strip()


def verify_qr_in_db(qr_value):
    try:
        conn, source = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM students WHERE student_no = %s", (qr_value,))
        result = cur.fetchone()
        cur.close()
        conn.close()

        exists = result is not None

        return exists, source

    except psycopg2.Error as e:
        return False, "error"

    except Exception as e:
        return False, "error"