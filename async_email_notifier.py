from datetime import datetime
from email.message import EmailMessage
import asyncio
import threading
from aiosmtplib import SMTP
from utils import get_connection


SMTP_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "user": "citadel.project00@gmail.com",
    "password": "ljcx sgug xwob grtw",
    "tls": True
}


async def send_login_email(guardian_email: str, student_name: str, timestamp: str):
    msg = EmailMessage()
    msg["From"] = SMTP_CONFIG["user"]
    msg["To"] = guardian_email
    msg["Subject"] = f"{student_name} Just Entered UCC Bagong Silang"
    msg.set_content(
        f"Your child {student_name} entered the campus on {timestamp}."
    )

    smtp = SMTP(hostname=SMTP_CONFIG["host"], port=SMTP_CONFIG["port"], start_tls=SMTP_CONFIG.get("tls", True))
    await smtp.connect()
    await smtp.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
    await smtp.send_message(msg)
    await smtp.quit()


async def notify_parent(student_no: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT fullname, guardian_email
        FROM students
        WHERE student_no = %s
    """, (student_no,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if not result:
        print(f"No student found with student_no {student_no}")
        return

    student_name, guardian_email = result
    if not guardian_email:
        print(f"No guardian email for student {student_name}")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await send_login_email(guardian_email, student_name, timestamp)



def notify_parent_task(student_no: str):
    def runner():
        asyncio.run(notify_parent(student_no))
    threading.Thread(target=runner, daemon=True).start()
