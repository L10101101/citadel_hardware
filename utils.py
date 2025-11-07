import psycopg2
from datetime import datetime
from db_utils import get_connection

def lookup_student(student_no):
    conn, _ = get_connection()
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

    if not row:
        return None

    name, program, year, section = row
    year_section = f"{year}-{section}" if year and section else ""
    return name, program, year_section


def log_to_entry_logs(student_no, last_logged, set_status=None, method_id=None):
    try:
        now = datetime.now()
        conn, _ = get_connection()
        cur = conn.cursor()

        cur.execute("SET TIME ZONE 'Asia/Manila'")

        cur.execute("""
            SELECT timestamps
            FROM entry_logs
            WHERE student_no = %s
            ORDER BY timestamps DESC
            LIMIT 1
        """, (student_no,))
        row_entry = cur.fetchone()
        last_entry_ts = row_entry[0] if row_entry else None

        cur.execute("""
            SELECT timestamps
            FROM exit_logs
            WHERE student_no = %s
            ORDER BY timestamps DESC
            LIMIT 1
        """, (student_no,))
        row_exit = cur.fetchone()
        last_exit_ts = row_exit[0] if row_exit else None

        if last_exit_ts and last_entry_ts and last_entry_ts >= last_exit_ts:
            if set_status:
                set_status("Already Logged Entry", "#FF6666")
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

        formatted_ts = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
        cur.execute("""
            INSERT INTO entry_logs (student_no, timestamps, method_id)
            VALUES (%s, %s, %s)
        """, (student_no, formatted_ts, method_id))
        conn.commit()

        if set_status:
            set_status("Access Granted", "#77EE77")

        cur.close()
        conn.close()
        return True

    except psycopg2.Error as e:
        if set_status:
            set_status("DB Error", "#FF6666")
        print("Entry log error:", e)
        return False

    
def log_to_exit_logs(student_no, last_logged, set_status=None, method_id=None):
    try:
        now = datetime.now()
        conn, _ = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT timestamps
            FROM entry_logs
            WHERE student_no = %s
            ORDER BY timestamps DESC
            LIMIT 1
        """, (student_no,))
        row_entry = cur.fetchone()
        last_entry_ts = row_entry[0] if row_entry else None

        cur.execute("""
            SELECT timestamps
            FROM exit_logs
            WHERE student_no = %s
            ORDER BY timestamps DESC
            LIMIT 1
        """, (student_no,))
        row_exit = cur.fetchone()
        last_exit_ts = row_exit[0] if row_exit else None

        if last_entry_ts is None:
            if set_status:
                set_status("No Entry Found", "#FF6666")
            cur.close()
            conn.close()
            return False

        if last_exit_ts and last_exit_ts >= last_entry_ts:
            if set_status:
                set_status("Already Logged Exit", "#FF6666")
            cur.close()
            conn.close()
            return False

        cur.execute("""
            INSERT INTO exit_logs (student_no, timestamps, method_id)
            VALUES (%s, %s, %s)
        """, (student_no, now, method_id))
        conn.commit()

        if set_status:
            set_status("Exit Logged", "#77EE77")

        cur.close()
        conn.close()
        last_logged[student_no] = now
        return True

    except Exception as e:
        if set_status:
            set_status("DB Error", "#FF6666")
        print("Exit log error:", e)
        return False
