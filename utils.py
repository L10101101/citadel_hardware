import os
import sys

from datetime import datetime, timedelta
from db_utils import get_connection

COOLDOWN = timedelta(minutes=0.5)

def get_base_path() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def resource_path(rel_path: str) -> str:
    return os.path.join(get_base_path(), rel_path.replace("/", os.sep))

_sync_manager = None

def set_sync_manager(sync_manager):
    global _sync_manager
    _sync_manager = sync_manager

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
    conn, _ = get_connection("local")
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'Asia/Manila'")

    student = lookup_student(student_no)
    if not student:
        if set_status:
            set_status("Student Not Enrolled", "#FF6666")
        cur.close(); conn.close()
        return False

    cur.execute("""
        SELECT entry_timestamp, exit_timestamp
        FROM monitoring_logs
        WHERE student_no = %s AND entry_timestamp IS NOT NULL
        ORDER BY entry_timestamp DESC
        LIMIT 1
    """, (student_no,))
    
    last_row = cur.fetchone()
    last_entry_time = last_row[0] if last_row else None
    last_exit_time = last_row[1] if last_row and len(last_row) > 1 else None
    if last_entry_time and last_entry_time.tzinfo:
        last_entry_time = last_entry_time.replace(tzinfo=None)
    if last_exit_time and last_exit_time.tzinfo:
        last_exit_time = last_exit_time.replace(tzinfo=None)

    if last_entry_time and last_exit_time is None:
        if set_status:
            set_status("Entry Already Logged", "#FF6666")
        cur.close(); conn.close()
        return False

    # Cooldown after exit: must wait before re-entry
    if last_exit_time is not None and now - last_exit_time < COOLDOWN:
        if set_status:
            set_status("Cannot Enter Yet", "#FF6666")
        cur.close(); conn.close()
        return False

    cur.execute("""
        INSERT INTO monitoring_logs (student_no, entry_method, entry_timestamp, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (student_no) DO UPDATE SET
            entry_method = EXCLUDED.entry_method,
            entry_timestamp = EXCLUDED.entry_timestamp,
            exit_method = NULL,
            exit_timestamp = NULL,
            updated_at = EXCLUDED.updated_at
    """, (student_no, method_id, now, now, now))
    
    conn.commit()

    if set_status:
        set_status("Entry Logged", "#77EE77")

    if _sync_manager:
        _sync_manager.queue_log_upload('entry', student_no, now, method_id, 'present')

    cur.close(); conn.close()
    return True

def log_exit(student_no, method_id, set_status=None):
    now = datetime.now()
    conn, _ = get_connection("local")
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'Asia/Manila'")

    student = lookup_student(student_no)
    if not student:
        if set_status:
            set_status("Student Not Enrolled", "#FF6666")
        cur.close(); conn.close()
        return False

    cur.execute("""
        SELECT entry_timestamp, exit_timestamp
        FROM monitoring_logs
        WHERE student_no = %s AND entry_timestamp IS NOT NULL
        ORDER BY entry_timestamp DESC
        LIMIT 1
    """, (student_no,))
    
    last_row = cur.fetchone()
    if not last_row:
        if set_status:
            set_status("No Entry Logged", "#FF6666")
        cur.close(); conn.close()
        return False

    last_entry_time = last_row[0]
    last_exit_time = last_row[1] if len(last_row) > 1 else None
    if last_entry_time and last_entry_time.tzinfo:
        last_entry_time = last_entry_time.replace(tzinfo=None)
    if last_exit_time and last_exit_time.tzinfo:
        last_exit_time = last_exit_time.replace(tzinfo=None)

    if last_exit_time is not None and last_exit_time >= last_entry_time:
        if set_status:
            set_status("Exit Already Logged", "#FF6666")
        cur.close(); conn.close()
        return False

    if now - last_entry_time < COOLDOWN:
        if set_status:
            set_status("Cannot Exit Yet", "#FF6666")
        cur.close(); conn.close()
        return False
    
    cur.execute("""
        INSERT INTO monitoring_logs (student_no, exit_method, exit_timestamp, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (student_no) DO UPDATE SET
            exit_method = EXCLUDED.exit_method,
            exit_timestamp = EXCLUDED.exit_timestamp,
            updated_at = EXCLUDED.updated_at
    """, (student_no, method_id, now, now, now))
    
    conn.commit()

    label = "Exit Logged" if method_id != 3 else "QR Exit Logged"
    if set_status:
        set_status(label, "#77EE77")

    if _sync_manager:
        _sync_manager.queue_log_upload('exit', student_no, now, method_id, 'exit')

    cur.close(); conn.close()
    return True

def get_current_status(student_no):
    conn, _ = get_connection("local")
    cur = conn.cursor()
    
    cur.execute("""
        SELECT entry_timestamp, exit_timestamp
        FROM monitoring_logs
        WHERE student_no = %s
        LIMIT 1
    """, (student_no,))
    
    result = cur.fetchone()
    cur.close(); conn.close()
    
    if not result:
        return None, None
    
    entry_ts, exit_ts = result
    status = "exited" if exit_ts else "entered"
    last_ts = exit_ts or entry_ts
    return status, last_ts