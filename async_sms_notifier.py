import os
import asyncio
import threading

from twilio.rest import Client
from db_utils import get_connection
from config_store import get_twilio_config
from datetime import datetime

def _get_twilio_client():
    cfg = get_twilio_config()
    if not cfg.get("account_sid") or not cfg.get("auth_token"):
        return None
    return Client(cfg["account_sid"], cfg["auth_token"])

async def send_sms(guardian_number: str, student_name: str, action: str):
    try:
        client = _get_twilio_client()
        if not client:
            return

        cfg = get_twilio_config()
        messaging_sid = cfg.get("messaging_sid")
        if not messaging_sid:
            return

        timestamp = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
        message = f"Your child {student_name} has {action} the campus.\nTime: {timestamp}"

        msg_params = {
            "body": message,
            "to": guardian_number,
            "messaging_service_sid": messaging_sid,
        }
        client.messages.create(**msg_params)

    except Exception as e:
        print(f"[SMS ERROR] Failed {e}")

async def notify_parent_sms(student_no: str, action: str = "entered"):
    try:
        conn, source = get_connection("local")
        cur = conn.cursor()
        cur.execute("""
            SELECT fullname, guardian_contact
            FROM students
            WHERE student_no = %s
        """, (student_no,))
        result = cur.fetchone()
        cur.close()
        conn.close()

        if not result:
            print(f"[WARNING] Not Found {student_no}")
            return

        student_name, guardian_phone = result
        if not guardian_phone:
            print(f"[WARNING] No Contact {student_name}")
            return

        if not guardian_phone.startswith("+"):
            guardian_phone = "+63" + guardian_phone.lstrip("0")

        await send_sms(guardian_phone, student_name, action)

    except Exception as e:
        print(f"[DB/SMS ERROR] {e}")
        if conn:
            conn.close()

def notify_parent_sms_task(student_no: str, action: str = "entered"):
    def runner():
        asyncio.run(notify_parent_sms(student_no, action))
    threading.Thread(target=runner, daemon=True).start()

def notify_entry_sms(student_no: str):
    notify_parent_sms_task(student_no, "entered")

def notify_exit_sms(student_no: str):
    notify_parent_sms_task(student_no, "exited")