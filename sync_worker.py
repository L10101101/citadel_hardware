import threading
import time
import json
from db_utils import get_connection

def sync_to_cloud(interval=10):
    while True:
        try:
            local_conn, local_source = get_connection()
            if local_source != "local":
                from db_utils import LOCAL_DB
                import psycopg2
                local_conn = psycopg2.connect(**LOCAL_DB)
            local_cur = local_conn.cursor()

            local_cur.execute(
                "SELECT id, table_name, payload FROM sync_queue WHERE synced = 0 ORDER BY id ASC LIMIT 20"
            )
            rows = local_cur.fetchall()

            if not rows:
                local_cur.close()
                local_conn.close()
                time.sleep(interval)
                continue

            cloud_conn, cloud_source = get_connection()
            if cloud_source != "cloud":
                local_cur.close()
                local_conn.close()
                time.sleep(interval)
                continue
            cloud_cur = cloud_conn.cursor()

            for sync_id, table_name, payload in rows:
                data = json.loads(payload)

                if table_name == "attendance_logs":
                    cloud_cur.execute("""
                        INSERT INTO attendance_logs (student_no, time_in, time_out, method_id)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (student_no, time_in)
                        DO UPDATE SET time_out = EXCLUDED.time_out
                    """, (
                        data["student_no"],
                        data["time_in"],
                        data["time_out"],
                        data["method_id"]
                    ))

                local_cur.execute(
                    "UPDATE sync_queue SET synced = TRUE WHERE id = %s", (sync_id,)
                )

            cloud_conn.commit()
            local_conn.commit()

            cloud_cur.close()
            cloud_conn.close()
            local_cur.close()
            local_conn.close()

        except Exception as e:
            print("[Sync Worker] Error:", e)
            time.sleep(interval)


def start_sync_worker(interval=10):
    t = threading.Thread(target=sync_to_cloud, args=(interval,), daemon=True)
    t.start()


"""CREATE TABLE sync_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    operation TEXT NOT NULL,  -- 'insert' or 'update'
    synced BOOLEAN DEFAULT 0,
    payload JSONB
);"""