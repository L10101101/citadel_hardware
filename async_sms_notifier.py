import asyncio
import threading
import logging

from twilio.rest import Client
from db_utils import get_connection
from config_store import get_twilio_config
from datetime import datetime

logger = logging.getLogger(__name__)


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
        logger.error("SMS send failed: %s", e)


async def notify_parent_sms(student_no: str, action: str = "entered"):
    conn = None
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

        if not result:
            logger.warning("Student not found for SMS notification: %s", student_no)
            return

        student_name, guardian_phone = result
        if not guardian_phone:
            logger.warning("No guardian contact for student: %s", student_name)
            return

        if not guardian_phone.startswith("+"):
            guardian_phone = "+63" + guardian_phone.lstrip("0")

        await send_sms(guardian_phone, student_name, action)

    except Exception:
        logger.exception("SMS notification failed")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def notify_parent_sms_task(student_no: str, action: str = "entered"):
    def runner():
        asyncio.run(notify_parent_sms(student_no, action))
    threading.Thread(target=runner, daemon=True).start()


def notify_entry_sms(student_no: str):
    notify_parent_sms_task(student_no, "entered")


def notify_exit_sms(student_no: str):
    notify_parent_sms_task(student_no, "exited")
