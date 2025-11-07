import psycopg2
from datetime import datetime


DB_CONFIG = {
    "dbname": "citadel_db",
    "user": "postgres",
    "password": "postgres",
    "host": "127.0.0.1",
    "port": 5432
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def lookup_student(student_no):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.fullname,
               p.program_name AS program,
               y.year_level,
               y.section
        FROM students s
        LEFT JOIN programs p ON s.program_id = p.id
        LEFT JOIN year_sections y ON s.year_section_id = y.id
        WHERE s.student_no = %s
    """, (student_no,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row if row else None


def log_to_entry_logs(student_no, last_logged, set_status=None, method_id=None):
    try:
        now = datetime.now()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT timestamps
            FROM entry_logs
            WHERE student_no = %s
            ORDER BY timestamps DESC
            LIMIT 1
        """, (student_no,))
        row = cur.fetchone()
        last_ts = row[0] if row else None

        last_time = last_logged.get(student_no)
        last_check = last_time or last_ts
        if last_check and (now - last_check).total_seconds() < 60:
            if set_status:
                set_status("Wait", "#FFBF66")
            cur.close()
            conn.close()
            return False

        student = lookup_student(student_no)
        if not student:
            if set_status:
                set_status("Access Denied", "#FF6666")
            cur.close()
            conn.close()
            return False

        cur.execute("""
            INSERT INTO entry_logs (student_no, timestamps, method_id)
            VALUES (%s, NOW(), %s)
        """, (student_no, method_id))
        conn.commit()

        if set_status:
            set_status("Access Granted", "#77EE77")

        cur.close()
        conn.close()
        last_logged[student_no] = now
        return True

    except psycopg2.Error as e:
        if set_status:
            set_status("DB Error", "#FF6666")
        return False
