import psycopg2
from datetime import datetime
from db_utils import get_connection

def lookup_student(student_no):
    conn, source = get_connection()  # ✅ unpack the tuple
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
        conn, source = get_connection()
        cur = conn.cursor()

        # Ensure timezone for the session
        cur.execute("SET TIME ZONE 'Asia/Manila'")

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

        # Format timestamp to "MM/DD/YYYY hh:mm:ss AM/PM" (Asia/Manila)
        formatted_ts = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")

        # Insert formatted string timestamp
        cur.execute("""
            INSERT INTO entry_logs (student_no, timestamps, method_id)
            VALUES (%s, %s, %s)
        """, (student_no, formatted_ts, method_id))
        conn.commit()

        if set_status:
            set_status("Access Granted", "#77EE77")

        cur.close()
        conn.close()
        last_logged[student_no] = now

        print(f"[LOG] Recorded entry for {student_no} ({source.upper()}) at {formatted_ts}")
        return True

    except psycopg2.Error as e:
        if set_status:
            set_status("DB Error", "#FF6666")
        print(f"[LOG ERROR] {e}")
        return False