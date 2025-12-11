import psycopg2
from datetime import datetime, timedelta
from db_utils import get_connection

COOLDOWN = timedelta(minutes=1)

def lookup_student(student_no):
    conn, _ = get_connection("local")
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


def log_entry(student_no, method_id, set_status=None):
    now = datetime.now()
    conn, _ = get_connection("cloud")
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'Asia/Manila'")

    # Check student
    student = lookup_student(student_no)
    if not student:
        if set_status:
            set_status("Access Denied", "#FF6666")
        cur.close(); conn.close()
        return False

    # Fetch existing data
    cur.execute("""
        SELECT entry_timestamp, exit_timestamp
        FROM monitoring_logs
        WHERE student_no = %s
    """, (student_no,))
    row = cur.fetchone()
    last_entry, last_exit = row if row else (None, None)

    # REQUIREMENT:
    # Entry allowed when:
    #  - No previous entry
    #  - OR last exit is newer than last entry (meaning already exited)
    if last_entry is not None and (last_exit is None or last_exit < last_entry):
        # Still inside
        if set_status:
            set_status("Already Inside", "#FF6666")
        cur.close(); conn.close()
        return False

    # Cooldown after exit
    if last_exit and now - last_exit < COOLDOWN:
        if set_status:
            set_status("Cannot Enter Yet", "#FF6666")
        cur.close(); conn.close()
        return False

    # Log entry
    cur.execute("""
        INSERT INTO monitoring_logs (student_no, entry_timestamp, entry_method_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (student_no) DO UPDATE
        SET entry_timestamp = EXCLUDED.entry_timestamp,
            entry_method_id = EXCLUDED.entry_method_id
    """, (student_no, now, method_id))
    conn.commit()

    if set_status:
        set_status("Entry Logged", "#77EE77")

    cur.close(); conn.close()
    return True

def log_exit(student_no, method_id, set_status=None):
    now = datetime.now()
    conn, _ = get_connection("cloud")
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'Asia/Manila'")

    # Check student
    student = lookup_student(student_no)
    if not student:
        if set_status:
            set_status("Access Denied", "#FF6666")
        cur.close(); conn.close()
        return False

    # Get timestamps
    cur.execute("""
        SELECT entry_timestamp, exit_timestamp
        FROM monitoring_logs
        WHERE student_no = %s
    """, (student_no,))
    row = cur.fetchone()
    last_entry, last_exit = row if row else (None, None)

    if last_entry is None:
        if set_status:
            set_status("No Entry Logged", "#FF6666")
        cur.close(); conn.close()
        return False

    if last_exit and last_exit >= last_entry:
        if set_status:
            set_status("Already Exited", "#FF6666")
        cur.close(); conn.close()
        return False

    # Cooldown after entry
    if now - last_entry < COOLDOWN:
        if set_status:
            set_status("Cannot Exit Yet", "#FF6666")
        cur.close(); conn.close()
        return False

    # Log exit
    cur.execute("""
        INSERT INTO monitoring_logs (student_no, exit_timestamp, exit_method_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (student_no) DO UPDATE
        SET exit_timestamp = EXCLUDED.exit_timestamp,
            exit_method_id = EXCLUDED.exit_method_id
    """, (student_no, now, method_id))
    conn.commit()

    label = "Exit Logged" if method_id != 3 else "QR Exit Logged"
    if set_status:
        set_status(label, "#77EE77")

    cur.close(); conn.close()
    return True
