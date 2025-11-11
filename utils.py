import json
from datetime import datetime
from db_utils import get_connection

def lookup_student(student_no):
    conn, source = get_connection()
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


def log_attendance(student_no, last_logged=None, set_status=None, method_id=None):
    try:
        now = datetime.now()

        conn, _ = get_connection()
        cur = conn.cursor()

        cur.execute("SET TIME ZONE 'Asia/Manila'")

        student = lookup_student(student_no)
        if not student:
            if set_status:
                set_status("Access Denied", "#FF6666")
            cur.close()
            conn.close()
            return False

        cur.execute("""
            SELECT id, time_in, time_out
            FROM attendance_logs
            WHERE student_no = %s
            ORDER BY time_in DESC
            LIMIT 1
        """, (student_no,))
        latest = cur.fetchone()

        record_data = {
            "student_no": student_no,
            "time_in": None,
            "time_out": None,
            "method_id": method_id,
        }

        if latest:
            log_id, time_in, time_out = latest
            if time_in and not time_out:
                cur.execute("UPDATE attendance_logs SET time_out = %s WHERE id = %s", (now, log_id))
                record_data["time_out"] = now.isoformat()
                operation = "update"
            else:
                cur.execute("""
                    INSERT INTO attendance_logs (student_no, time_in, method_id)
                    VALUES (%s, %s, %s)
                    RETURNING id
                """, (student_no, now, method_id))
                log_id = cur.fetchone()[0]
                record_data["time_in"] = now.isoformat()
                operation = "insert"
        else:
            cur.execute("""
                INSERT INTO attendance_logs (student_no, time_in, method_id)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (student_no, now, method_id))
            log_id = cur.fetchone()[0]
            record_data["time_in"] = now.isoformat()
            operation = "insert"

        conn.commit()

        cur.execute("""
            INSERT INTO sync_queue (table_name, record_id, operation, payload, synced)
            VALUES ('attendance_logs', %s, %s, %s, 0)
        """, (log_id, operation, json.dumps(record_data)))
        conn.commit()

        if set_status:
            set_status("Attendance Recorded", "#77EE77")

        if last_logged is not None:
            last_logged[student_no] = now

        cur.close()
        conn.close()
        return True

    except Exception as e:
        if set_status:
            set_status("DB Error", "#FF6666")
        print("Attendance log error:", e)
        return False