import os
import re
import subprocess
import tempfile
import threading
import re
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable

from sync_queue import SyncQueue
from psycopg2.extras import execute_batch
from psycopg2 import Binary
from db_utils import (
    get_cloud_connection,
    get_local_connection,
    has_internet,
    LOCAL_DB,
    CLOUD_DB,
)
from sync_helpers import (
    local_needs_schema,
    sync_schema_from_cloud,
    sync_reference_tables,
    sync_verification_methods,
)
from config_store import get_sync_config

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtCore import QTimer
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

class DataSyncManager:
    def __init__(
        self,
        sync_interval: int | None = None,
        upload_interval: int | None = None,
        sync_slideshow: bool = True,
    ):
        self._sync_config = get_sync_config()
        cfg_interval = self._sync_config.get("sync_interval", 300)
        cfg_upload = self._sync_config.get("upload_interval", 60)
        cfg_monitoring_pull = self._sync_config.get("monitoring_pull_interval", 30)
        cfg_monitoring_full_pull = self._sync_config.get("monitoring_full_pull_interval", 300)
        cfg_monitoring_delta_lookback = self._sync_config.get("monitoring_delta_lookback_seconds", 86400)
        self.sync_interval = sync_interval if sync_interval is not None else cfg_interval
        self.upload_interval = upload_interval if upload_interval is not None else cfg_upload
        self.monitoring_pull_interval = max(5, int(cfg_monitoring_pull))
        self.monitoring_full_pull_interval = max(30, int(cfg_monitoring_full_pull))
        self.monitoring_delta_lookback_seconds = max(60, int(cfg_monitoring_delta_lookback))
        self.sync_slideshow = bool(sync_slideshow)
        self.sync_queue = SyncQueue()
        self.running = False
        self.sync_thread = None
        self.upload_thread = None
        self.last_sync_time = None
        self.last_upload_time = None
        self.last_monitoring_pull = None
        self.last_monitoring_sync = None
        self.last_monitoring_full_pull = None
        self._monitoring_updated_at_warning_emitted = False
        
        self.last_student_sync = None
        self.last_fingerprint_sync = None
        self.last_facial_sync = None
        
        self.on_sync_start: Optional[Callable] = None
        self.on_sync_progress: Optional[Callable] = None
        self.on_sync_complete: Optional[Callable] = None
        self.on_sync_error: Optional[Callable] = None
        
        self.is_syncing = False
        self.sync_progress = ""
        self.startup_sync_attempted = False

    @staticmethod
    def _safe_ident(value: str, fallback: str) -> str:
        if not value:
            return fallback
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
            return value
        return fallback

    def _get_sync_config(self) -> dict:
        return self._sync_config or {}
    def _safe_callback(self, callback: Optional[Callable], *args):
        if callback is None:
            return
        
        if QT_AVAILABLE:
            def execute_callback():
                try:
                    if callback:
                        callback(*args)
                except Exception:
                    pass
            
            QTimer.singleShot(0, execute_callback)
        else:
            # Fallback if Qt not available (shouldn't happen in this app)
            try:
                if callback:
                    callback(*args)
            except Exception:
                pass
    
    def start(self):
        """Start background sync threads"""
        if self.running:
            return
        
        self.running = True
        self.sync_thread = threading.Thread(target=self._sync_worker, daemon=True)
        self.upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.sync_thread.start()
        self.upload_thread.start()
    
    def stop(self):
        """Stop background sync threads"""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
        if self.upload_thread:
            self.upload_thread.join(timeout=5)
    
    def sync_now(self, force_full: bool = False, background: bool = True):
        """
        Trigger immediate sync
        
        Args:
            force_full: Force full sync instead of incremental
            background: Run in background thread (default True to prevent blocking)
        """
        # Check if already syncing
        if self.is_syncing:
            return False
        
        # Check internet connection
        if not has_internet():
            self._safe_callback(self.on_sync_error, "No internet connection")
            # Mark startup sync as attempted even if failed (so worker can proceed)
            if force_full:
                self.startup_sync_attempted = True
            return False
        
        if background:
            # Run in background thread to prevent blocking
            sync_thread = threading.Thread(
                target=self._sync_in_thread,
                args=(force_full,),
                daemon=True
            )
            sync_thread.start()
            return True
        else:
            # Direct call (should only be used from background worker)
            return self._sync_in_thread(force_full)
    
    def _sync_in_thread(self, force_full: bool):
        """Internal sync method that runs in background thread."""
        self.is_syncing = True
        try:
            self._safe_callback(self.on_sync_start)

            if force_full:
                result = self._full_sync()
            else:
                result = self._incremental_sync()
            # Mark startup sync as attempted once we have tried a full sync
            if force_full:
                self.startup_sync_attempted = True

            if result:
                self._safe_callback(self.on_sync_complete)
            else:
                self._safe_callback(self.on_sync_error, "Sync failed")

            return result
        except Exception as e:
            self._safe_callback(self.on_sync_error, str(e))
            if force_full:
                self.startup_sync_attempted = True
            return False
        finally:
            self.is_syncing = False
    
    def _sync_worker(self):
        """Background worker for downloading data from cloud"""
        while self.running:
            try:
                # Wait for startup sync to complete before periodic syncs
                if not self.startup_sync_attempted:
                    time.sleep(5)  # Check more frequently until startup sync is attempted
                    continue
                
                if has_internet() and not self.is_syncing:
                    # Periodic cloud->local pull for kiosk state convergence.
                    if (
                        not self.last_monitoring_pull
                        or (datetime.now() - self.last_monitoring_pull).total_seconds() >= self.monitoring_pull_interval
                    ):
                        force_full_monitoring_pull = (
                            not self.last_monitoring_full_pull
                            or (datetime.now() - self.last_monitoring_full_pull).total_seconds()
                            >= self.monitoring_full_pull_interval
                        )
                        if self._sync_monitoring_logs_only(force_full=force_full_monitoring_pull):
                            self.last_monitoring_pull = datetime.now()
                            if force_full_monitoring_pull:
                                self.last_monitoring_full_pull = self.last_monitoring_pull

                    # Check if it's time for periodic sync
                    if (self.last_sync_time and 
                        (datetime.now() - self.last_sync_time).total_seconds() >= self.sync_interval):
                        # Incremental sync removed; run a full sync instead
                        self.sync_now(background=False, force_full=True)
                time.sleep(30)  # Check every 30 seconds
            except Exception:
                time.sleep(60)

    def _sync_monitoring_logs_only(self, force_full: bool = False) -> bool:
        """Pull monitoring_logs updates from cloud into local cache."""
        cloud_conn = None
        local_conn = None
        cloud_cur = None
        local_cur = None
        try:
            cloud_conn, _ = get_cloud_connection()
            local_conn, _ = get_local_connection()
            cloud_cur = cloud_conn.cursor()
            local_cur = local_conn.cursor()
            cloud_cur.execute("SET TIME ZONE 'Asia/Manila'")
            local_cur.execute("SET TIME ZONE 'Asia/Manila'")

            table = "monitoring_logs"
            updated_col = "updated_at"

            cloud_cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
            )
            cloud_cols = {row[0] for row in cloud_cur.fetchall()}
            local_cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
            )
            local_cols = {row[0] for row in local_cur.fetchall()}

            if "student_no" not in cloud_cols or "student_no" not in local_cols:
                return False
            has_local_pending_upload = "pending_upload" in local_cols

            columns = [
                "id",
                "student_no",
                "entry_method",
                "entry_timestamp",
                "exit_method",
                "exit_timestamp",
                "created_at",
                "updated_at",
            ]
            columns = [c for c in columns if c in cloud_cols and c in local_cols]
            if not columns:
                return False

            cols_sql = ", ".join(f'"{c}"' for c in columns)
            sync_candidates = [c for c in ("updated_at", "entry_timestamp", "exit_timestamp", "created_at") if c in columns]
            sync_token_expr = None
            if sync_candidates:
                sync_token_expr = "GREATEST(" + ", ".join(
                    [f'COALESCE("{c}", to_timestamp(0))' for c in sync_candidates]
                ) + ")"

            if sync_token_expr and self.last_monitoring_sync and not force_full:
                floor_ts = self.last_monitoring_sync - timedelta(seconds=self.monitoring_delta_lookback_seconds)
                cloud_cur.execute(
                    f"""
                    SELECT {cols_sql}, {sync_token_expr} AS "__sync_token"
                    FROM "{table}"
                    WHERE {sync_token_expr} > %s
                    ORDER BY "__sync_token" ASC
                    """,
                    (floor_ts,),
                )
            elif sync_token_expr:
                cloud_cur.execute(
                    f"""
                    SELECT {cols_sql}, {sync_token_expr} AS "__sync_token"
                    FROM "{table}"
                    ORDER BY "__sync_token" ASC
                    """
                )
            else:
                cloud_cur.execute(
                    f"""
                    SELECT {cols_sql}
                    FROM "{table}"
                    ORDER BY student_no ASC
                    """
                )

            rows = cloud_cur.fetchall()
            if not rows:
                return True

            has_sync_token = bool(sync_token_expr)
            data_rows = [r[:-1] for r in rows] if has_sync_token else rows

            has_id = "id" in columns
            student_no_idx = columns.index("student_no")
            id_idx = columns.index("id") if has_id else -1
            if has_id:
                # Align local IDs to cloud IDs when safe (no conflict with another local row).
                for row in data_rows:
                    row_id = row[id_idx]
                    student_no = row[student_no_idx]
                    if row_id is None or student_no is None:
                        continue
                    local_cur.execute(
                        """
                        UPDATE monitoring_logs t
                        SET id = %s
                        WHERE t.student_no = %s
                          AND t.id IS DISTINCT FROM %s
                          AND NOT EXISTS (
                              SELECT 1
                              FROM monitoring_logs m2
                              WHERE m2.id = %s
                                AND m2.student_no <> %s
                          )
                        """,
                        (row_id, student_no, row_id, row_id, student_no),
                    )

            insert_cols = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join("%s" for _ in columns)
            update_cols = [c for c in columns if c not in ("student_no", "id")]
            if update_cols:
                set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
                where_parts = []
                if "updated_at" in columns:
                    where_parts.append(
                        f'"{table}"."updated_at" IS NULL OR EXCLUDED."updated_at" >= "{table}"."updated_at"'
                    )
                if has_local_pending_upload:
                    where_parts.append(f'COALESCE("{table}"."pending_upload", FALSE) = FALSE')
                where_clause = f"\n                    WHERE {' AND '.join(where_parts)}" if where_parts else ""
                upsert_sql = f"""
                    INSERT INTO "{table}" ({insert_cols})
                    VALUES ({placeholders})
                    ON CONFLICT (student_no) DO UPDATE SET
                        {set_clause}{where_clause}
                """
            else:
                upsert_sql = f"""
                    INSERT INTO "{table}" ({insert_cols})
                    VALUES ({placeholders})
                    ON CONFLICT (student_no) DO NOTHING
                """

            for row in data_rows:
                local_cur.execute(upsert_sql, row)
            local_conn.commit()

            if has_sync_token:
                latest = max((r[-1] for r in rows if r[-1] is not None), default=None)
                if latest is not None:
                    self.last_monitoring_sync = latest
            elif updated_col in columns:
                updated_idx = columns.index(updated_col)
                latest = max((r[updated_idx] for r in data_rows if r[updated_idx] is not None), default=None)
                if latest is not None:
                    self.last_monitoring_sync = latest
            return True
        except Exception:
            if local_conn:
                try:
                    local_conn.rollback()
                except Exception:
                    pass
            return False
        finally:
            if cloud_cur:
                try:
                    cloud_cur.close()
                except Exception:
                    pass
            if local_cur:
                try:
                    local_cur.close()
                except Exception:
                    pass
            if cloud_conn:
                try:
                    cloud_conn.close()
                except Exception:
                    pass
            if local_conn:
                try:
                    local_conn.close()
                except Exception:
                    pass

    def _warn_if_monitoring_updated_at_not_timestamptz(self, cloud_conn, local_conn) -> None:
        """Emit a startup warning when monitoring_logs.updated_at is not timestamptz."""
        if self._monitoring_updated_at_warning_emitted:
            return

        def _column_type(conn, table: str, column: str):
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
                    """,
                    (table, column),
                )
                return cur.fetchone()
            finally:
                cur.close()

        try:
            cloud_type = _column_type(cloud_conn, "monitoring_logs", "updated_at")
            local_type = _column_type(local_conn, "monitoring_logs", "updated_at")
            cloud_ok = bool(cloud_type and cloud_type[1] == "timestamptz")
            local_ok = bool(local_type and local_type[1] == "timestamptz")
            if not (cloud_ok and local_ok):
                self._update_progress(
                    "Warning: monitoring_logs.updated_at should be TIMESTAMPTZ on cloud and local for reliable time-based pulls."
                )
                self._monitoring_updated_at_warning_emitted = True
        except Exception:
            pass
    
    def _upload_worker(self):
        """Background worker for uploading logs to cloud"""
        while self.running:
            try:
                if has_internet():
                    self._upload_pending_logs()
                time.sleep(self.upload_interval)
            except Exception:
                time.sleep(60)

    def _sync_verification_methods(self, cloud_conn, local_conn):
        """Sync verification_methods lookup table from cloud to local."""
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()
        try:
            try:
                cfg = self._get_sync_config().get("verification_methods", {})
                table = self._safe_ident(cfg.get("table"), "verification_methods")
                id_col = self._safe_ident(cfg.get("id_column"), "id")
                method_col = self._safe_ident(cfg.get("method_column"), "method")
                cloud_cur.execute(
                    f"""
                    SELECT "{id_col}", "{method_col}"
                    FROM "{table}"
                    ORDER BY "{id_col}"
                    """
                )
                rows = cloud_cur.fetchall()

                for vid, vmethod in rows:
                    local_cur.execute(
                        f"""
                        INSERT INTO "{table}" ("{id_col}", "{method_col}")
                        VALUES (%s, %s)
                        ON CONFLICT ("{id_col}") DO UPDATE SET
                            "{method_col}" = EXCLUDED."{method_col}"
                        """,
                        (vid, vmethod),
                    )

                # Targeted delete: remove local rows not in cloud (archived/removed)
                if rows:
                    cloud_ids = [r[0] for r in rows]
                    local_cur.execute(
                        f'DELETE FROM "{table}" WHERE ("{id_col}" IS NULL OR NOT ("{id_col}" = ANY(%s)))',
                        (cloud_ids,),
                    )
                else:
                    local_cur.execute(f'DELETE FROM "{table}"')
                local_conn.commit()
            except Exception:
                local_conn.rollback()
        finally:
            cloud_cur.close()
            local_cur.close()

    def _sync_slideshow(self, cloud_conn, local_conn):
        """Sync slideshow images from cloud to local (full sync only)."""
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()
        try:
            try:
                local_cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS slideshow (
                        id INTEGER PRIMARY KEY,
                        image BYTEA NOT NULL
                    )
                    """
                )
            except Exception:
                pass

            cloud_cur.execute('SELECT id, image FROM slideshow ORDER BY id')
            rows = cloud_cur.fetchall()

            if not rows:
                local_cur.execute('DELETE FROM slideshow')
                local_conn.commit()
                return

            for slide_id, image in rows:
                local_cur.execute(
                    """
                    INSERT INTO slideshow (id, image)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        image = EXCLUDED.image
                    """,
                    (slide_id, Binary(image)),
                )

            cloud_ids = [r[0] for r in rows]
            local_cur.execute(
                'DELETE FROM slideshow WHERE (id IS NULL OR NOT (id = ANY(%s)))',
                (cloud_ids,),
            )
            local_conn.commit()
        except Exception:
            local_conn.rollback()
        finally:
            cloud_cur.close()
            local_cur.close()

    def _sync_full_table(self, cloud_cur, local_cur, table_name: str, pk_column: str = "id"):
        """Sync a reference table from cloud to local using all columns that exist in both.
        Copies full rows so no column is left NULL when the cloud has a value.
        """
        cloud_cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        cloud_cols = [row[0] for row in cloud_cur.fetchall()]
        if not cloud_cols:
            return
        local_cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        local_cols_set = {row[0] for row in local_cur.fetchall()}
        columns = [c for c in cloud_cols if c in local_cols_set]
        if not columns or pk_column not in columns:
            return
        cols_quoted = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join("%s" for _ in columns)
        update_cols = [c for c in columns if c != pk_column]
        cloud_cur.execute(f'SELECT {cols_quoted} FROM "{table_name}" ORDER BY "{pk_column}"')
        rows = cloud_cur.fetchall()
        if not rows:
            try:
                local_cur.execute(f'DELETE FROM "{table_name}"')
            except Exception:
                pass
            return
        if update_cols:
            set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
            sql = f"""
                INSERT INTO "{table_name}" ({cols_quoted})
                VALUES ({placeholders})
                ON CONFLICT ("{pk_column}") DO UPDATE SET {set_clause}
            """
        else:
            sql = f"""
                INSERT INTO "{table_name}" ({cols_quoted})
                VALUES ({placeholders})
                ON CONFLICT ("{pk_column}") DO NOTHING
            """
        for row in rows:
            local_cur.execute(sql, row)

        # Targeted delete: remove local rows not in cloud (archived/removed)
        pk_index = columns.index(pk_column)
        cloud_pks = [row[pk_index] for row in rows]
        local_cur.execute(
            f'DELETE FROM "{table_name}" WHERE ("{pk_column}" IS NULL OR NOT ("{pk_column}" = ANY(%s)))',
            (cloud_pks,),
        )

    def _sync_reference_tables(self, cloud_conn, local_conn):
        """Sync reference tables (programs, year_sections) from cloud to local with all columns.
        Colleges are not synced to local. Order: programs (students FK), then year_sections.
        """
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()
        cfg = self._get_sync_config()
        ref_tables = cfg.get("reference_tables") or ("programs", "year_sections")
        if isinstance(ref_tables, str):
            ref_tables = [t.strip() for t in ref_tables.split(",") if t.strip()]
        safe_tables = []
        for t in ref_tables:
            safe_tables.append(self._safe_ident(t, ""))
        ref_tables = [t for t in safe_tables if t]
        try:
            try:
                for table in ref_tables:
                    local_cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s AND is_nullable = 'NO'
                    """, (table,))
                    non_null_cols = [row[0] for row in local_cur.fetchall()] or []
                    local_cur.execute("""
                        SELECT a.attname
                        FROM pg_index i
                        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = %s::regclass AND i.indisprimary
                    """, (table,))
                    pk_cols = {row[0] for row in local_cur.fetchall()} or set()
                    for col in non_null_cols:
                        if col in pk_cols:
                            continue
                        try:
                            local_cur.execute(f'ALTER TABLE {table} ALTER COLUMN "{col}" DROP NOT NULL')
                        except Exception:
                            continue
            except Exception:
                pass

            for table in ref_tables:
                try:
                    self._sync_full_table(cloud_cur, local_cur, table, "id")
                except Exception:
                    pass

            local_conn.commit()
        except Exception:
            local_conn.rollback()
        finally:
            cloud_cur.close()
            local_cur.close()
    
    def _local_needs_schema(self) -> bool:
        """Return True if local DB is missing key tables (e.g. students)."""
        try:
            local_conn, _ = get_local_connection()
            cur = local_conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'students'
            """)
            exists = cur.fetchone()[0] > 0
            cur.close()
            local_conn.close()
            return not exists
        except Exception:
            return True  # assume needs schema on error

    def _strip_fk_constraints_from_schema_sql(self, schema_path: str) -> None:
        """
        Rewrite schema SQL in-place to remove foreign key constraints.
        Local DB is used as a read cache; FKs would block load order and are not needed.
        """
        with open(schema_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # 1. Remove ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... REFERENCES ... ;
        content = re.sub(
            r"ALTER\s+TABLE\s+[^;]*?\bADD\s+CONSTRAINT\s+[^;]*?\bFOREIGN\s+KEY\s+[^;]*?;",
            "-- (FK constraint removed for local cache)\n",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # 2. Remove inline REFERENCES in column definitions (e.g. "col integer REFERENCES t(id)")
        content = re.sub(
            r"\s+REFERENCES\s+\S+\s*\([^)]*\)(\s+ON\s+(DELETE|UPDATE)\s+\w+)*",
            "",
            content,
            flags=re.IGNORECASE,
        )

        # 3. Remove CONSTRAINT ... FOREIGN KEY ... REFERENCES inside CREATE TABLE (table-level FK)
        content = re.sub(
            r",\s*CONSTRAINT\s+\w+\s+FOREIGN\s+KEY\s*\([^)]*\)\s+REFERENCES\s+\S+\s*\([^)]*\)(\s+ON\s+(DELETE|UPDATE)\s+\w+)*",
            "",
            content,
            flags=re.IGNORECASE,
        )

        with open(schema_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _sync_schema_from_cloud(self) -> bool:
        """Dump schema from cloud and apply to local via pg_dump/psql (without FK constraints). Returns True on success."""
        dump_exe = "pg_dump"
        psql_exe = "psql"
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sql", delete=False
            ) as f:
                schema_path = f.name
        except Exception:
            return False

        try:
            # Build env for pg_dump (cloud)
            env = os.environ.copy()
            env["PGPASSWORD"] = str(CLOUD_DB.get("password") or "")
            env["PGHOST"] = str(CLOUD_DB.get("host") or "")
            env["PGPORT"] = str(CLOUD_DB.get("port") or "5432")
            env["PGDATABASE"] = str(CLOUD_DB.get("dbname") or "postgres")
            env["PGUSER"] = str(CLOUD_DB.get("user") or "")
            for k, v in (
                ("PGSSLMODE", CLOUD_DB.get("sslmode")),
                ("PGSSLROOTCERT", CLOUD_DB.get("sslrootcert")),
                ("PGSSLCERT", CLOUD_DB.get("sslcert")),
                ("PGSSLKEY", CLOUD_DB.get("sslkey")),
            ):
                if v:
                    env[k] = str(v)

            cmd_dump = [
                dump_exe,
                "-h", env["PGHOST"],
                "-p", env["PGPORT"],
                "-U", env["PGUSER"],
                "-d", env["PGDATABASE"],
                "--schema-only",
                "--no-owner",
                "--no-privileges",
                "-f", schema_path,
            ]
            run_kwargs = {
                "capture_output": True,
                "text": True,
                "timeout": 120,
            }
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                run_kwargs["startupinfo"] = startupinfo
                run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            r = subprocess.run(cmd_dump, env=env, **run_kwargs)
            if r.returncode != 0:
                return False

            # Strip FK constraints so local can load schema/data in any order
            self._strip_fk_constraints_from_schema_sql(schema_path)

            # Apply to local via psql
            env_local = os.environ.copy()
            env_local["PGPASSWORD"] = str(LOCAL_DB.get("password") or "")
            env_local["PGHOST"] = str(LOCAL_DB.get("host") or "127.0.0.1")
            env_local["PGPORT"] = str(LOCAL_DB.get("port") or "5432")
            env_local["PGDATABASE"] = str(LOCAL_DB.get("dbname") or "postgres")
            env_local["PGUSER"] = str(LOCAL_DB.get("user") or "")

            cmd_psql = [
                psql_exe,
                "-h", env_local["PGHOST"],
                "-p", env_local["PGPORT"],
                "-U", env_local["PGUSER"],
                "-d", env_local["PGDATABASE"],
                "-f", schema_path,
            ]
            r = subprocess.run(cmd_psql, env=env_local, **run_kwargs)
            if r.returncode != 0:
                pass  # "already exists" etc.; continue with data sync
            return True
        except subprocess.TimeoutExpired:
            return False
        except FileNotFoundError:
            return False
        except Exception:
            return False
        finally:
            try:
                os.unlink(schema_path)
            except Exception:
                pass

    def _full_sync(self) -> bool:
        """Perform full synchronization from cloud to local"""
        try:
            self._update_progress("Connecting to cloud...")
            cloud_conn, _ = get_cloud_connection()
            local_conn, _ = get_local_connection()
            self._warn_if_monitoring_updated_at_not_timestamptz(cloud_conn, local_conn)
            
            if self._local_needs_schema():
                self._update_progress("Syncing schema from cloud...")
                self._sync_schema_from_cloud()
            
            # Ensure reference tables (programs, year_sections, etc.) are populated
            self._update_progress("Syncing reference data...")
            self._sync_reference_tables(cloud_conn, local_conn)

            # Sync verification methods lookup table
            self._update_progress("Syncing verification methods...")
            self._sync_verification_methods(cloud_conn, local_conn)
            
            # Sync students
            self._update_progress("Syncing students...")
            self._sync_students(cloud_conn, local_conn, full=True)
            
            # Sync fingerprints
            self._update_progress("Syncing fingerprints...")
            self._sync_fingerprints(cloud_conn, local_conn, full=True)
            
            # Sync facial recognition data
            self._update_progress("Syncing facial data...")
            self._sync_facial_data(cloud_conn, local_conn, full=True)

            # Sync slideshow images (optional per app context).
            if self.sync_slideshow:
                self._update_progress("Syncing slideshow...")
                self._sync_slideshow(cloud_conn, local_conn)
            
            cloud_conn.close()
            local_conn.close()
            
            self.last_sync_time = datetime.now()
            self._update_progress("Sync complete")
            return True
            
        except Exception as e:
            self._update_progress(f"Sync failed: {e}")
            return False

    def _incremental_sync(self) -> bool:
        """Perform incremental sync for students and fingerprints after idle periods."""
        try:
            self._update_progress("Connecting to cloud...")
            cloud_conn, _ = get_cloud_connection()
            local_conn, _ = get_local_connection()

            if self._local_needs_schema():
                self._update_progress("Syncing schema from cloud...")
                self._sync_schema_from_cloud()

            self._update_progress("Syncing students (incremental)...")
            self._sync_students(cloud_conn, local_conn, full=False)

            self._update_progress("Syncing fingerprints (incremental)...")
            self._sync_fingerprints(cloud_conn, local_conn, full=False)

            cloud_conn.close()
            local_conn.close()

            self.last_sync_time = datetime.now()
            self._update_progress("Sync complete")
            return True
        except Exception as e:
            self._update_progress(f"Sync failed: {e}")
            return False
    
    def _update_progress(self, message: str):
        """Update sync progress message"""
        self.sync_progress = message
        self._safe_callback(self.on_sync_progress, message)
    
    def _sync_students(self, cloud_conn, local_conn, full: bool = False):
        """Sync student data from cloud to local"""
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()
        cfg = self._get_sync_config().get("students", {})
        students_table = self._safe_ident(cfg.get("table"), "students")
        updated_col = self._safe_ident(cfg.get("updated_at_column"), "updated_at")
        facial_data_col = self._safe_ident(cfg.get("facial_data_column"), "facial_recognition_data")
        facial_flag_col = self._safe_ident(cfg.get("facial_flag_column"), "has_facial_recognition")
        
        try:
            # Ensure local schema is permissive enough to accept cloud rows.
            # Cloud data may have NULL in optional fields; local should not be
            # stricter than the cloud source.
            try:
                # Relax NOT NULL on all non-key student columns so that the local
                # cache is not stricter than the cloud schema. We keep NOT NULL
                # only on the primary key (student_no).
                local_cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s
                      AND is_nullable = 'NO'
                    """,
                    (students_table,),
                )
                non_null_cols = [row[0] for row in local_cur.fetchall()] or []

                # Detect primary key columns (usually just student_no)
                local_cur.execute(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = %s::regclass
                      AND i.indisprimary
                    """,
                    (students_table,),
                )
                pk_cols = {row[0] for row in local_cur.fetchall()} or set()

                for col in non_null_cols:
                    if col in pk_cols:
                        continue  # keep NOT NULL on primary key columns
                    try:
                        local_cur.execute(
                            f'ALTER TABLE "{students_table}" ALTER COLUMN "{col}" DROP NOT NULL'
                        )
                    except Exception:
                        # Ignore per-column failures; we'll still attempt sync
                        continue

                # Drop non-primary-key UNIQUE constraints so local isn't stricter
                # than the cloud schema (e.g. students_email_unique).
                try:
                    local_cur.execute(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid = %s::regclass
                          AND contype = 'u'
                        """,
                        (students_table,),
                    )
                    for (conname,) in local_cur.fetchall():
                        try:
                            local_cur.execute(
                                f'ALTER TABLE "{students_table}" DROP CONSTRAINT "{conname}"'
                            )
                        except Exception:
                            # Ignore per-constraint failures.
                            continue
                except Exception:
                    # Non-fatal; if this fails we still attempt the sync.
                    pass
            except Exception:
                # Non-fatal: if this fails we still attempt the sync and let
                # the concrete error surface if needed.
                pass

            # Check if cloud and local both have id column so we copy cloud id to local
            cloud_cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (students_table,),
            )
            cloud_student_cols = {row[0] for row in cloud_cur.fetchall()}
            local_cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (students_table,),
            )
            local_student_cols = {row[0] for row in local_cur.fetchall()}
            include_id = "id" in cloud_student_cols and "id" in local_student_cols

            if include_id:
                base_select = f"""
                    SELECT
                        s.id,
                        s.student_no,
                        s.fullname,
                        s.program_id,
                        s.year_section_id,
                        s.status,
                        s.dob,
                        s.gender,
                        s.email,
                        s.contact,
                        s.address,
                        s.guardian_name,
                        s.guardian_contact,
                        s.guardian_email,
                        s.guardian_address,
                        s.username,
                        s.password,
                        s.created_at,
                        s."{updated_col}",
                        s."{facial_flag_col}",
                        s."{facial_data_col}"
                    FROM "{students_table}" s
                """
                updated_at_index = 18
            else:
                base_select = f"""
                    SELECT
                        s.student_no,
                        s.fullname,
                        s.program_id,
                        s.year_section_id,
                        s.status,
                        s.dob,
                        s.gender,
                        s.email,
                        s.contact,
                        s.address,
                        s.guardian_name,
                        s.guardian_contact,
                        s.guardian_email,
                        s.guardian_address,
                        s.username,
                        s.password,
                        s.created_at,
                        s."{updated_col}",
                        s."{facial_flag_col}",
                        s."{facial_data_col}"
                    FROM "{students_table}" s
                """
                updated_at_index = 17

            if full:
                # Full sync: get all students
                cloud_cur.execute(base_select + f' ORDER BY s."{updated_col}" DESC')
            else:
                # Incremental sync: only get updated students
                if self.last_student_sync:
                    cloud_cur.execute(
                        base_select + f' WHERE s."{updated_col}" > %s ORDER BY s."{updated_col}" DESC',
                        (self.last_student_sync,),
                    )
                else:
                    # No previous sync timestamp, sync all (but still incremental mode)
                    cloud_cur.execute(base_select + f' ORDER BY s."{updated_col}" DESC')
            
            students = cloud_cur.fetchall()
            if not students:
                return

            # Batch insert/update to local
            # NOTE: Local connection uses autocommit=True, so using
            # "ON COMMIT DROP" would immediately drop the temp table
            # after creation. We therefore omit it so the temp table
            # lives for the lifetime of the connection.
            if include_id:
                local_cur.execute("""
                    CREATE TEMP TABLE temp_students (
                        id BIGINT,
                        student_no VARCHAR PRIMARY KEY,
                        fullname VARCHAR,
                        program_id BIGINT,
                        year_section_id BIGINT,
                        status VARCHAR,
                        dob DATE,
                        gender VARCHAR,
                        email VARCHAR,
                        contact VARCHAR,
                        address VARCHAR,
                        guardian_name VARCHAR,
                        guardian_contact VARCHAR,
                        guardian_email VARCHAR,
                        guardian_address VARCHAR,
                        username VARCHAR,
                        password VARCHAR,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP,
                        has_facial_recognition BOOLEAN,
                        facial_recognition_data BYTEA
                    )
                """)
                execute_batch(local_cur, """
                    INSERT INTO temp_students (
                        id, student_no, fullname, program_id, year_section_id, status,
                        dob, gender, email, contact, address,
                        guardian_name, guardian_contact, guardian_email, guardian_address,
                        username, password, created_at, updated_at,
                        has_facial_recognition, facial_recognition_data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, students)
                local_cur.execute(f"""
                    INSERT INTO "{students_table}" (
                        id, student_no, fullname, program_id, year_section_id, status,
                        dob, gender, email, contact, address,
                        guardian_name, guardian_contact, guardian_email, guardian_address,
                        username, password, created_at, updated_at,
                        has_facial_recognition, facial_recognition_data
                    )
                    SELECT
                        id, student_no, fullname, program_id, year_section_id, status,
                        dob, gender, email, contact, address,
                        guardian_name, guardian_contact, guardian_email, guardian_address,
                        username, password, created_at, updated_at,
                        has_facial_recognition, facial_recognition_data
                    FROM temp_students
                    ON CONFLICT (id) DO NOTHING
                """)
            else:
                local_cur.execute("""
                    CREATE TEMP TABLE temp_students (
                        student_no VARCHAR PRIMARY KEY,
                        fullname VARCHAR,
                        program_id BIGINT,
                        year_section_id BIGINT,
                        status VARCHAR,
                        dob DATE,
                        gender VARCHAR,
                        email VARCHAR,
                        contact VARCHAR,
                        address VARCHAR,
                        guardian_name VARCHAR,
                        guardian_contact VARCHAR,
                        guardian_email VARCHAR,
                        guardian_address VARCHAR,
                        username VARCHAR,
                        password VARCHAR,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP,
                        has_facial_recognition BOOLEAN,
                        facial_recognition_data BYTEA
                    )
                """)
                execute_batch(local_cur, """
                    INSERT INTO temp_students (
                        student_no, fullname, program_id, year_section_id, status,
                        dob, gender, email, contact, address,
                        guardian_name, guardian_contact, guardian_email, guardian_address,
                        username, password, created_at, updated_at,
                        has_facial_recognition, facial_recognition_data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, students)
                local_cur.execute(f"""
                    INSERT INTO "{students_table}" (
                        student_no, fullname, program_id, year_section_id, status,
                        dob, gender, email, contact, address,
                        guardian_name, guardian_contact, guardian_email, guardian_address,
                        username, password, created_at, updated_at,
                        has_facial_recognition, facial_recognition_data
                    )
                    SELECT
                        student_no, fullname, program_id, year_section_id, status,
                        dob, gender, email, contact, address,
                        guardian_name, guardian_contact, guardian_email, guardian_address,
                        username, password, created_at, updated_at,
                        has_facial_recognition, facial_recognition_data
                    FROM temp_students
                    ON CONFLICT (student_no) DO NOTHING
                """)
            local_conn.commit()
            
            # Update last sync time (updated_at index depends on whether we selected id)
            self.last_student_sync = max(s[updated_at_index] for s in students) if students else self.last_student_sync
            
        except Exception:
            local_conn.rollback()
        finally:
            cloud_cur.close()
            local_cur.close()
    
    def _sync_fingerprints(self, cloud_conn, local_conn, full: bool = False):
        """Sync fingerprint templates from cloud to local"""
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()
        cfg = self._get_sync_config().get("fingerprints", {})
        fp_table = self._safe_ident(cfg.get("table"), "fingerprints")
        fp_updated_col = self._safe_ident(cfg.get("updated_at_column"), "updated_at")
        fp_template_col = self._safe_ident(cfg.get("template_column"), "template")
        
        try:
            # Detect whether cloud schema has an updated_at column on fingerprints.
            # Older cloud schemas may not have it; in that case we synthesize
            # a timestamp and ensure the local table has an updated_at column.
            has_updated_at = getattr(self, "_fingerprints_has_updated_at", None)
            if has_updated_at is None:
                cloud_cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_name = %s AND column_name = %s
                    """,
                    (fp_table, fp_updated_col),
                )
                has_updated_at = cloud_cur.fetchone()[0] > 0
                self._fingerprints_has_updated_at = has_updated_at

            if has_updated_at:
                if full:
                    cloud_cur.execute(
                        f"""
                        SELECT student_no, "{fp_template_col}", "{fp_updated_col}"
                        FROM "{fp_table}"
                        ORDER BY "{fp_updated_col}" DESC
                        """
                    )
                else:
                    if self.last_fingerprint_sync:
                        cloud_cur.execute(
                            f"""
                            SELECT student_no, "{fp_template_col}", "{fp_updated_col}"
                            FROM "{fp_table}"
                            WHERE "{fp_updated_col}" > %s
                            ORDER BY "{fp_updated_col}" DESC
                            """,
                            (self.last_fingerprint_sync,),
                        )
                    else:
                        # No previous sync timestamp, sync all (but still incremental mode)
                        cloud_cur.execute(
                            f"""
                            SELECT student_no, "{fp_template_col}", "{fp_updated_col}"
                            FROM "{fp_table}"
                            ORDER BY "{fp_updated_col}" DESC
                            """
                        )
            else:
                # Cloud fingerprints table has no updated_at column.
                # We synthesize a timestamp so local side can still
                # use updated_at for ordering and conflict resolution.
                if full or not self.last_fingerprint_sync:
                    cloud_cur.execute(
                        f"""
                        SELECT student_no,
                               "{fp_template_col}",
                               NOW() AS "{fp_updated_col}"
                        FROM "{fp_table}"
                        ORDER BY student_no
                        """
                    )
                else:
                    # Without updated_at in cloud, incremental filtering
                    # is not possible; fall back to full set.
                    cloud_cur.execute(
                        f"""
                        SELECT student_no,
                               "{fp_template_col}",
                               NOW() AS "{fp_updated_col}"
                        FROM "{fp_table}"
                        ORDER BY student_no
                        """
                    )
            
            fingerprints = cloud_cur.fetchall()
            if not fingerprints:
                return

            # Ensure local fingerprints table has the expected updated_at column
            try:
                local_cur.execute(
                    f"""
                    ALTER TABLE IF EXISTS "{fp_table}"
                    ADD COLUMN IF NOT EXISTS "{fp_updated_col}" TIMESTAMP
                    """
                )
            except Exception:
                # Non-fatal; if this fails, the subsequent INSERT will report the issue
                pass
            
            # Batch upsert fingerprints
            for student_no, template, updated_at in fingerprints:
                local_cur.execute(
                    f"""
                    INSERT INTO "{fp_table}" (student_no, "{fp_template_col}", "{fp_updated_col}")
                    VALUES (%s, %s, %s)
                    ON CONFLICT (student_no) DO NOTHING
                    """,
                    (student_no, Binary(template), updated_at),
                )
            local_conn.commit()
            
            self.last_fingerprint_sync = max(f[2] for f in fingerprints) if fingerprints else self.last_fingerprint_sync
            
        except Exception:
            local_conn.rollback()
        finally:
            cloud_cur.close()
            local_cur.close()
    
    def _sync_facial_data(self, cloud_conn, local_conn, full: bool = False):
        """Sync facial recognition data from cloud to local"""
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()
        cfg = self._get_sync_config().get("students", {})
        students_table = self._safe_ident(cfg.get("table"), "students")
        updated_col = self._safe_ident(cfg.get("updated_at_column"), "updated_at")
        facial_data_col = self._safe_ident(cfg.get("facial_data_column"), "facial_recognition_data")
        facial_flag_col = self._safe_ident(cfg.get("facial_flag_column"), "has_facial_recognition")
        
        try:
            if full:
                cloud_cur.execute(
                    f"""
                    SELECT student_no, "{facial_data_col}", "{facial_flag_col}", "{updated_col}"
                    FROM "{students_table}"
                    WHERE "{facial_flag_col}" = TRUE
                    ORDER BY "{updated_col}" DESC
                    """
                )
            else:
                if self.last_facial_sync:
                    cloud_cur.execute(
                        f"""
                        SELECT student_no, "{facial_data_col}", "{facial_flag_col}", "{updated_col}"
                        FROM "{students_table}"
                        WHERE "{facial_flag_col}" = TRUE AND "{updated_col}" > %s
                        ORDER BY "{updated_col}" DESC
                        """,
                        (self.last_facial_sync,),
                    )
                else:
                    # No previous sync timestamp, sync all (but still incremental mode)
                    cloud_cur.execute(
                        f"""
                        SELECT student_no, "{facial_data_col}", "{facial_flag_col}", "{updated_col}"
                        FROM "{students_table}"
                        WHERE "{facial_flag_col}" = TRUE
                        ORDER BY "{updated_col}" DESC
                        """
                    )
            
            facial_data = cloud_cur.fetchall()
            if not facial_data:
                local_cur.execute(
                    f"""UPDATE "{students_table}"
                       SET "{facial_flag_col}" = FALSE, "{facial_data_col}" = NULL
                       WHERE "{facial_flag_col}" = TRUE"""
                )
                local_conn.commit()
                return

            # Full sync: clear all local facial data first, then set only those in cloud
            if full:
                local_cur.execute(
                    f"""UPDATE "{students_table}"
                       SET "{facial_flag_col}" = FALSE, "{facial_data_col}" = NULL
                       WHERE "{facial_flag_col}" = TRUE"""
                )

            # Batch update facial data
            for student_no, facial_data_blob, has_facial, updated_at in facial_data:
                local_cur.execute(
                    f"""
                    UPDATE "{students_table}"
                    SET "{facial_data_col}" = %s,
                        "{facial_flag_col}" = %s,
                        "{updated_col}" = %s
                    WHERE student_no = %s
                    """,
                    (Binary(facial_data_blob) if facial_data_blob else None,
                     has_facial, updated_at, student_no),
                )
            # Clear facial data on local students that no longer have it in cloud (incremental only)
            if not full:
                cloud_cur.execute(
                    f'SELECT student_no FROM "{students_table}" WHERE "{facial_flag_col}" = TRUE'
                )
                cloud_facial_nos = [row[0] for row in cloud_cur.fetchall()]
                if cloud_facial_nos:
                    local_cur.execute(
                        f"""UPDATE "{students_table}"
                           SET "{facial_flag_col}" = FALSE, "{facial_data_col}" = NULL
                           WHERE "{facial_flag_col}" = TRUE
                             AND (student_no IS NULL OR NOT (student_no = ANY(%s)))""",
                        (cloud_facial_nos,),
                    )
                else:
                    local_cur.execute(
                        f"""UPDATE "{students_table}"
                           SET "{facial_flag_col}" = FALSE, "{facial_data_col}" = NULL
                           WHERE "{facial_flag_col}" = TRUE"""
                    )
            local_conn.commit()
            
            self.last_facial_sync = max(f[3] for f in facial_data) if facial_data else self.last_facial_sync
            
        except Exception:
            local_conn.rollback()
        finally:
            cloud_cur.close()
            local_cur.close()
    
    def queue_log_upload(self, log_type: str, student_no: str, timestamp: datetime, 
                        method_id: int, status: str = 'present'):
        """Queue a log entry for upload to cloud"""
        self.sync_queue.add('log_entry', {
            'log_type': log_type,  # 'entry' or 'exit'
            'student_no': student_no,
            'timestamp': timestamp,
            'method_id': method_id,
            'status': status
        })
    
    def _save_failed_upload(self, log_data: dict):
        """Save failed upload to local database for later retry"""
        try:
            local_conn, _ = get_local_connection()
            local_cur = local_conn.cursor()
            
            # Create table if it doesn't exist
            local_cur.execute("""
                CREATE TABLE IF NOT EXISTS failed_uploads (
                    id SERIAL PRIMARY KEY,
                    log_type VARCHAR(50) NOT NULL,
                    student_no VARCHAR(255) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    method_id INTEGER NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    retry_count INTEGER DEFAULT 0,
                    UNIQUE(student_no, timestamp, log_type)
                )
            """)
            
            # Insert failed upload
            local_cur.execute("""
                INSERT INTO failed_uploads (log_type, student_no, timestamp, method_id, status, retry_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_no, timestamp, log_type) DO UPDATE SET
                    retry_count = failed_uploads.retry_count + 1,
                    created_at = CURRENT_TIMESTAMP
            """, (log_data['log_type'], log_data['student_no'], log_data['timestamp'], 
                  log_data['method_id'], log_data['status'], log_data.get('retry_count', 0)))
            
            local_conn.commit()
            local_cur.close()
            local_conn.close()
        except Exception as e:
            logger.warning(
                "Failed to persist failed upload (student_no=%s, type=%s): %s",
                log_data.get("student_no"),
                log_data.get("log_type"),
                e,
            )
    
    def _retry_failed_uploads(self):
        """Retry uploading logs from failed_uploads table"""
        try:
            local_conn, _ = get_local_connection()
            local_cur = local_conn.cursor()
            
            # Check if table exists
            local_cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'failed_uploads'
            """)
            if local_cur.fetchone()[0] == 0:
                local_cur.close()
                local_conn.close()
                return
            
            # Get failed uploads (limit to prevent memory issues)
            local_cur.execute("""
                SELECT log_type, student_no, timestamp, method_id, status, id
                FROM failed_uploads
                ORDER BY created_at ASC
                LIMIT 50
            """)
            
            failed_logs = local_cur.fetchall()
            local_cur.close()
            local_conn.close()
            
            if not failed_logs:
                return
            
            uploaded_count = 0
            for log_type, student_no, timestamp, method_id, status, failed_id in failed_logs:
                log_data = {
                    'log_type': log_type,
                    'student_no': student_no,
                    'timestamp': timestamp,
                    'method_id': method_id,
                    'status': status
                }
                
                success = self._upload_log_entry(log_data)
                if success:
                    # Remove from failed_uploads on success
                    try:
                        local_conn, _ = get_local_connection()
                        local_cur = local_conn.cursor()
                        local_cur.execute("DELETE FROM failed_uploads WHERE id = %s", (failed_id,))
                        local_conn.commit()
                        local_cur.close()
                        local_conn.close()
                        uploaded_count += 1
                    except Exception as e:
                        logger.warning("Failed to delete retried failed_upload row id=%s: %s", failed_id, e)
            if uploaded_count > 0:
                logger.info("Retried and uploaded %d previously failed log(s)", uploaded_count)
             
        except Exception as e:
            logger.warning("Retry failed_uploads pass encountered an error: %s", e)
    
    def _upload_pending_logs(self):
        """Upload pending logs from queue to cloud"""
        uploaded = 0
        failed = 0
        
        # First, try to retry any previously failed uploads
        self._retry_failed_uploads()
        
        while True:
            operation = self.sync_queue.get(timeout=1)
            if not operation:
                break
            
            try:
                if operation['type'] == 'log_entry':
                    success = self._upload_log_entry(operation['data'])
                    if success:
                        uploaded += 1
                    else:
                        failed += 1
                        # Retry logic
                        if operation['retry_count'] < 5:
                            operation['retry_count'] += 1
                            self.sync_queue.queue.put(operation)
                        else:
                            # Max retries reached - save to persistent storage (silent)
                            self._save_failed_upload(operation['data'])
                else:
                    failed += 1
                    
            except Exception as e:
                logger.warning("Queue upload operation failed (type=%s): %s", operation.get('type'), e)
                failed += 1
                if operation.get('retry_count', 0) < 5:
                    operation['retry_count'] = operation.get('retry_count', 0) + 1
                    self.sync_queue.queue.put(operation)
                else:
                    # Max retries reached - save to persistent storage
                    if 'data' in operation:
                        self._save_failed_upload(operation['data'])
        if uploaded or failed:
            logger.info("Upload queue cycle complete: uploaded=%d failed=%d", uploaded, failed)
        
    
    def _upload_log_entry(self, log_data: dict) -> bool:
        """Upload a single log entry to cloud"""
        cloud_conn = None
        cloud_cur = None
        try:
            cloud_conn, _ = get_cloud_connection()
            cloud_cur = cloud_conn.cursor()
            
            log_type = log_data['log_type']
            student_no = log_data['student_no']
            timestamp = log_data['timestamp']
            method_id = log_data['method_id']
            status = log_data['status']
            
            # Only write to monitoring_logs in the cloud (no attendance_logs / entry_logs / exit_logs)
            if log_type == 'entry':
                cloud_cur.execute("""
                    INSERT INTO monitoring_logs (
                        student_no, entry_method, entry_timestamp, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (student_no) DO UPDATE SET
                        entry_method    = EXCLUDED.entry_method,
                        entry_timestamp = EXCLUDED.entry_timestamp,
                        updated_at      = EXCLUDED.updated_at
                """, (student_no, method_id, timestamp, timestamp, timestamp))
            elif log_type == 'exit':
                cloud_cur.execute("""
                    INSERT INTO monitoring_logs (
                        student_no, exit_method, exit_timestamp, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (student_no) DO UPDATE SET
                        exit_method    = EXCLUDED.exit_method,
                        exit_timestamp = EXCLUDED.exit_timestamp,
                        updated_at     = EXCLUDED.updated_at
                """, (student_no, method_id, timestamp, timestamp, timestamp))
            
            cloud_conn.commit()
            cloud_cur.close()
            cloud_conn.close()
            
            self.last_upload_time = datetime.now()
            return True
            
        except Exception as e:
            logger.warning(
                "Cloud upload failed (student_no=%s, type=%s): %s",
                log_data.get("student_no"),
                log_data.get("log_type"),
                e,
            )
            if cloud_conn:
                try:
                    cloud_conn.rollback()
                except Exception:
                    pass
            return False
        finally:
            # Ensure cleanup
            if cloud_cur:
                try:
                    cloud_cur.close()
                except Exception:
                    pass
            if cloud_conn:
                try:
                    cloud_conn.close()
                except Exception:
                    pass
    
    def get_sync_status(self) -> dict:
        """Get current sync status"""
        return {
            'running': self.running,
            'last_sync': self.last_sync_time.isoformat() if self.last_sync_time else None,
            'last_upload': self.last_upload_time.isoformat() if self.last_upload_time else None,
            'pending_uploads': self.sync_queue.size(),
            'last_student_sync': self.last_student_sync.isoformat() if self.last_student_sync else None,
            'last_fingerprint_sync': self.last_fingerprint_sync.isoformat() if self.last_fingerprint_sync else None,
            'last_facial_sync': self.last_facial_sync.isoformat() if self.last_facial_sync else None
        }
