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
    """Checks if QR/student_no exists in either cloud or local DB."""
    try:
        conn, source = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM students WHERE student_no = %s", (qr_value,))
        result = cur.fetchone()
        cur.close()
        conn.close()

        exists = result is not None
        print(f"[QR] Checked {qr_value} in {source.upper()} database → {'VALID' if exists else 'NOT FOUND'}")

        return exists, source

    except psycopg2.Error as e:
        print(f"[QR] Database error: {e}")
        return False, "error"

    except Exception as e:
        print(f"[QR] Unexpected error: {e}")
        return False, "error"