import os
import sys
import re

from datetime import datetime, timedelta
from db_utils import get_connection
from status_labels import (
    status_cannot_enter_yet,
    status_cannot_exit_yet,
    status_cloud_unavailable,
    status_entry_already_logged,
    status_entry_logged,
    status_exit_logged,
    status_exit_already_logged,
    status_not_enrolled,
)

COOLDOWN = timedelta(seconds=10)


def format_program_label(program_name: str) -> str:
    if not program_name:
        return "-"
    text = str(program_name).strip()
    m = re.match(r"(?i)^\s*Bachelor\s+of\s+(.+?)(\s+in\s+.+)?\s*$", text)
    if m:
        degree_part = (m.group(1) or "").strip()
        rest = (m.group(2) or "").strip()
        initials = "".join(
            token[0].upper() for token in re.findall(r"[A-Za-z]+", degree_part)
        )
        if initials:
            text = f"B{initials}{(' ' + rest) if rest else ''}".strip()
    return text or "-"


def get_base_path() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(rel_path: str) -> str:
    return os.path.join(get_base_path(), rel_path.replace("/", os.sep))


def get_slideshow_images_local():
    try:
        conn, _ = get_connection("local")
        cur = conn.cursor()
        cur.execute("SELECT id, image FROM slideshow ORDER BY id")
        rows = cur.fetchall() or []
        cur.close()
        conn.close()
        images = []
        for _, data in rows:
            if data is None:
                continue
            if isinstance(data, memoryview):
                data = data.tobytes()
            images.append(data)
        return images
    except Exception:
        return []

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


def _get_latest_log(student_no):
    conn, _ = get_connection("local")
    cur = conn.cursor()
    cur.execute("""
        SELECT entry_timestamp, exit_timestamp
        FROM monitoring_logs
        WHERE student_no = %s AND entry_timestamp IS NOT NULL
        ORDER BY entry_timestamp DESC
        LIMIT 1
    """, (student_no,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None, None
    entry_ts, exit_ts = row
    if entry_ts and entry_ts.tzinfo:
        entry_ts = entry_ts.replace(tzinfo=None)
    if exit_ts and exit_ts.tzinfo:
        exit_ts = exit_ts.replace(tzinfo=None)
    return entry_ts, exit_ts


def get_next_action(student_no):
    try:
        entry_ts, exit_ts = _get_latest_log(student_no)
    except Exception:
        return "error", None
    if not entry_ts and not exit_ts:
        return "entry", None
    if entry_ts and (not exit_ts or entry_ts > exit_ts):
        return "exit", entry_ts
    if exit_ts and (not entry_ts or exit_ts > entry_ts):
        return "entry", exit_ts
    return "exit", max(entry_ts, exit_ts)


def can_attempt_entry(student_no, set_status=None):
    now = datetime.now()
    try:
        last_entry_time, last_exit_time = _get_latest_log(student_no)
    except Exception:
        if set_status:
            status_cloud_unavailable(set_status)
        return False

    if last_entry_time and last_exit_time is None:
        if set_status:
            status_entry_already_logged(set_status)
        return False

    if last_entry_time and last_exit_time:
        last_ts = max(last_entry_time, last_exit_time)
    else:
        last_ts = last_entry_time or last_exit_time

    if last_ts is not None and now - last_ts < COOLDOWN:
        if set_status:
            status_cannot_enter_yet(set_status)
        return False

    return True


def log_entry(student_no, method_id, set_status=None):
    now = datetime.now()
    conn, _ = get_connection("local")
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'Asia/Manila'")

    student = lookup_student(student_no)
    if not student:
        if set_status:
            status_not_enrolled(set_status)
        cur.close(); conn.close()
        return False

    try:
        last_entry_time, last_exit_time = _get_latest_log(student_no)
    except Exception:
        if set_status:
            status_cloud_unavailable(set_status)
        cur.close(); conn.close()
        return False

    if last_entry_time and last_exit_time is None:
        if set_status:
            status_entry_already_logged(set_status)
        cur.close(); conn.close()
        return False

    last_ts = None
    if last_entry_time and last_exit_time:
        last_ts = max(last_entry_time, last_exit_time)
    else:
        last_ts = last_entry_time or last_exit_time

    if last_ts is not None and now - last_ts < COOLDOWN:
        if set_status:
            status_cannot_enter_yet(set_status)
        cur.close(); conn.close()
        return False

    cur.execute("""
        INSERT INTO monitoring_logs (student_no, entry_method, entry_timestamp, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (student_no) DO UPDATE SET
            entry_method = EXCLUDED.entry_method,
            entry_timestamp = EXCLUDED.entry_timestamp,
            updated_at = EXCLUDED.updated_at
    """, (student_no, method_id, now, now, now))
    
    conn.commit()

    if set_status:
        status_entry_logged(set_status)

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
            status_not_enrolled(set_status)
        cur.close(); conn.close()
        return False

    try:
        last_entry_time, last_exit_time = _get_latest_log(student_no)
    except Exception:
        if set_status:
            status_cloud_unavailable(set_status)
        cur.close(); conn.close()
        return False

    if last_exit_time is not None and last_exit_time >= last_entry_time:
        if set_status:
            status_exit_already_logged(set_status)
        cur.close(); conn.close()
        return False

    last_ts = max(last_entry_time, last_exit_time) if last_exit_time else last_entry_time
    if last_ts and now - last_ts < COOLDOWN:
        if set_status:
            status_cannot_exit_yet(set_status)
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


    status_exit_logged(set_status)

    if _sync_manager:
        _sync_manager.queue_log_upload('exit', student_no, now, method_id, 'exit')

    cur.close(); conn.close()
    return True


def get_current_status(student_no):
    try:
        entry_ts, exit_ts = _get_latest_log(student_no)
    except Exception:
        return None, None
    if not entry_ts and not exit_ts:
        return None, None
    if entry_ts and (not exit_ts or entry_ts > exit_ts):
        return "entered", entry_ts
    return "exited", exit_ts


def _get_day_bounds(target_date=None):
    day = target_date or datetime.now().date()
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    return start, end


def get_daily_summary_counts(target_date=None):
    start, end = _get_day_bounds(target_date)
    try:
        conn, _ = get_connection("local")
        cur = conn.cursor()
        cur.execute("SET TIME ZONE 'Asia/Manila'")
        cur.execute(
            """
            SELECT
                SUM(
                    CASE
                        WHEN entry_timestamp >= %s
                             AND entry_timestamp < %s
                             AND (exit_timestamp IS NULL OR exit_timestamp < entry_timestamp)
                        THEN 1 ELSE 0
                    END
                ) AS in_campus,
                SUM(
                    CASE
                        WHEN exit_timestamp >= %s
                             AND exit_timestamp < %s
                             AND exit_timestamp >= entry_timestamp
                        THEN 1 ELSE 0
                    END
                ) AS out_campus
            FROM monitoring_logs
            """,
            (start, end, start, end),
        )
        row = cur.fetchone() or (0, 0)
        cur.close()
        conn.close()
        in_campus = int(row[0] or 0)
        out_campus = int(row[1] or 0)
        return in_campus, out_campus, in_campus + out_campus
    except Exception:
        return 0, 0, 0


def get_top_program_remaining(limit=3, target_date=None):
    start, end = _get_day_bounds(target_date)
    try:
        conn, _ = get_connection("local")
        cur = conn.cursor()
        cur.execute("SET TIME ZONE 'Asia/Manila'")
        cur.execute(
            """
            SELECT
                COALESCE(p.program_name, 'Unknown') AS program_name,
                COUNT(*) AS remaining
            FROM monitoring_logs m
            JOIN students s ON m.student_no = s.student_no
            LEFT JOIN programs p ON s.program_id = p.id
            WHERE m.entry_timestamp >= %s
              AND m.entry_timestamp < %s
              AND (m.exit_timestamp IS NULL OR m.exit_timestamp < m.entry_timestamp)
            GROUP BY COALESCE(p.program_name, 'Unknown')
            ORDER BY remaining DESC, program_name ASC
            LIMIT %s
            """,
            (start, end, limit),
        )
        rows = cur.fetchall() or []
        cur.close()
        conn.close()
        return [(row[0], int(row[1] or 0)) for row in rows]
    except Exception:
        return []


def get_program_remaining_counts(target_date=None):
    start, end = _get_day_bounds(target_date)
    try:
        conn, _ = get_connection("local")
        cur = conn.cursor()
        cur.execute("SET TIME ZONE 'Asia/Manila'")
        cur.execute(
            """
            SELECT
                COALESCE(p.program_name, 'Unknown') AS program_name,
                COUNT(*) AS remaining
            FROM monitoring_logs m
            JOIN students s ON m.student_no = s.student_no
            LEFT JOIN programs p ON s.program_id = p.id
            WHERE m.entry_timestamp >= %s
              AND m.entry_timestamp < %s
              AND (m.exit_timestamp IS NULL OR m.exit_timestamp < m.entry_timestamp)
            GROUP BY COALESCE(p.program_name, 'Unknown')
            ORDER BY remaining DESC, program_name ASC
            """,
            (start, end),
        )
        rows = cur.fetchall() or []
        cur.close()
        conn.close()
        return [(row[0], int(row[1] or 0)) for row in rows]
    except Exception:
        return []


def get_present_students_with_program(target_date=None):
    start, end = _get_day_bounds(target_date)
    try:
        conn, _ = get_connection("local")
        cur = conn.cursor()
        cur.execute("SET TIME ZONE 'Asia/Manila'")
        cur.execute(
            """
            SELECT
                COALESCE(s.fullname, 'Unknown') AS fullname,
                COALESCE(p.program_name, 'Unknown') AS program_name
            FROM monitoring_logs m
            JOIN students s ON m.student_no = s.student_no
            LEFT JOIN programs p ON s.program_id = p.id
            WHERE m.entry_timestamp >= %s
              AND m.entry_timestamp < %s
              AND (m.exit_timestamp IS NULL OR m.exit_timestamp < m.entry_timestamp)
            ORDER BY fullname ASC
            """,
            (start, end),
        )
        rows = cur.fetchall() or []
        cur.close()
        conn.close()
        return [(row[0], row[1]) for row in rows]
    except Exception:
        return []
