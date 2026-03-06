import asyncio
import threading
import logging
import json
from urllib import error as urlerror
from urllib import request as urlrequest

from db_utils import get_connection
from config_store import get_sms_app_config
from datetime import datetime

logger = logging.getLogger(__name__)


def _post_json(url: str, payload: dict, headers: dict, timeout_sec: int):
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url=url, data=body, headers=headers, method="POST")
    with urlrequest.urlopen(req, timeout=timeout_sec) as resp:
        _ = resp.read()
        return getattr(resp, "status", 200)


async def send_sms(guardian_number: str, student_name: str, action: str):
    try:
        cfg = get_sms_app_config()
        endpoint_url = (cfg.get("endpoint_url") or "").strip()
        if not endpoint_url:
            logger.debug("SMS app endpoint is not configured; SMS skipped.")
            return

        now = datetime.now()
        formatted_date = now.strftime("%A, %B %d, %Y")
        formatted_time = now.strftime("%I:%M %p")
        timestamp = now.strftime("%A, %B %d, %Y %I:%M %p")
        message = (
            f"This is to inform you that your child, {student_name}, has {action} "
            "the University of Caloocan City - Bagong Silang Campus.\n"
            f"Student Name: {student_name}\n"
            f"Date: {formatted_date}\n"
            f"Time: {formatted_time}"
        )

        payload = {
            "to": guardian_number,
            "message": message,
            "student_name": student_name,
            "action": action,
            "timestamp": timestamp,
        }
        sender_id = (cfg.get("sender_id") or "").strip()
        if sender_id:
            payload["sender_id"] = sender_id

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        api_key = (cfg.get("api_key") or "").strip()
        if api_key:
            headers["X-API-Key"] = api_key
            headers["Authorization"] = f"Bearer {api_key}"

        timeout_sec = int(cfg.get("timeout_sec", 10) or 10)
        status = await asyncio.to_thread(
            _post_json,
            endpoint_url,
            payload,
            headers,
            timeout_sec,
        )
        if int(status) >= 400:
            logger.error("SMS app returned HTTP %s for %s", status, guardian_number)
        else:
            logger.info("SMS sent via SMS app to %s", guardian_number)

    except urlerror.HTTPError as e:
        logger.error("SMS send failed with HTTP %s: %s", e.code, e.reason)
    except urlerror.URLError as e:
        logger.error("SMS send failed due to network error: %s", e.reason)
    except Exception as e:
        logger.error("SMS send failed: %s", e)


def _normalize_phone(guardian_phone: str) -> str:
    phone = (guardian_phone or "").strip()
    if not phone:
        return ""
    if phone.startswith("+"):
        return phone
    if phone.startswith("00"):
        return f"+{phone[2:]}"
    if phone.startswith("0"):
        return f"+63{phone[1:]}"
    return f"+{phone}"


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
        guardian_phone = _normalize_phone(guardian_phone)
        if not guardian_phone:
            logger.warning("No guardian contact for student: %s", student_name)
            return

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
