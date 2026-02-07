import os
import re
import subprocess
import tempfile
import threading
import time
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

try:
    from PyQt6.QtCore import QTimer
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

class DataSyncManager:
    def __init__(self, sync_interval: int = 300, upload_interval: int = 60):
        self.sync_interval = sync_interval
        self.upload_interval = upload_interval
        self.sync_queue = SyncQueue()
        self.running = False
        self.sync_thread = None
        self.upload_thread = None
        self.last_sync_time = None
        self.last_upload_time = None
        
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
        """Internal sync method that runs in background thread.

        Incremental sync has been removed; we always run a full sync.
        """
        self.is_syncing = True
        try:
            self._safe_callback(self.on_sync_start)

            # Always perform a full sync now
            result = self._full_sync()
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
                    # Check if it's time for periodic sync
                    if (self.last_sync_time and 
                        (datetime.now() - self.last_sync_time).total_seconds() >= self.sync_interval):
                        # Incremental sync removed; run a full sync instead
                        self.sync_now(background=False, force_full=True)
                time.sleep(30)  # Check every 30 seconds
            except Exception:
                time.sleep(60)
    
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
                cloud_cur.execute("""
                    SELECT id, method
                    FROM verification_methods
                    ORDER BY id
                """)
                rows = cloud_cur.fetchall()

                for vid, vmethod in rows:
                    local_cur.execute("""
                        INSERT INTO verification_methods (id, method)
                        VALUES (%s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            method = EXCLUDED.method
                    """, (vid, vmethod))

                # Targeted delete: remove local rows not in cloud (archived/removed)
                if rows:
                    cloud_ids = [r[0] for r in rows]
                    local_cur.execute(
                        "DELETE FROM verification_methods WHERE (id IS NULL OR NOT (id = ANY(%s)))",
                        (cloud_ids,),
                    )
                else:
                    local_cur.execute("DELETE FROM verification_methods")
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
        ref_tables = ("programs", "year_sections")
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
            r = subprocess.run(cmd_dump, env=env, capture_output=True, text=True, timeout=120)
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
            r = subprocess.run(cmd_psql, env=env_local, capture_output=True, text=True, timeout=120)
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
        
        try:
            # Ensure local schema is permissive enough to accept cloud rows.
            # Cloud data may have NULL in optional fields; local should not be
            # stricter than the cloud source.
            try:
                # Relax NOT NULL on all non-key student columns so that the local
                # cache is not stricter than the cloud schema. We keep NOT NULL
                # only on the primary key (student_no).
                local_cur.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'students'
                      AND is_nullable = 'NO'
                """)
                non_null_cols = [row[0] for row in local_cur.fetchall()] or []

                # Detect primary key columns (usually just student_no)
                local_cur.execute("""
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = 'students'::regclass
                      AND i.indisprimary
                """)
                pk_cols = {row[0] for row in local_cur.fetchall()} or set()

                for col in non_null_cols:
                    if col in pk_cols:
                        continue  # keep NOT NULL on primary key columns
                    try:
                        local_cur.execute(
                            f'ALTER TABLE students ALTER COLUMN "{col}" DROP NOT NULL'
                        )
                    except Exception:
                        # Ignore per-column failures; we'll still attempt sync
                        continue

                # Drop non-primary-key UNIQUE constraints so local isn't stricter
                # than the cloud schema (e.g. students_email_unique).
                try:
                    local_cur.execute("""
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid = 'students'::regclass
                          AND contype = 'u'
                    """)
                    for (conname,) in local_cur.fetchall():
                        try:
                            local_cur.execute(
                                f'ALTER TABLE "students" DROP CONSTRAINT "{conname}"'
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
            cloud_cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'students'
            """, ())
            cloud_student_cols = {row[0] for row in cloud_cur.fetchall()}
            local_cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'students'
            """, ())
            local_student_cols = {row[0] for row in local_cur.fetchall()}
            include_id = "id" in cloud_student_cols and "id" in local_student_cols

            if include_id:
                base_select = """
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
                        s.updated_at,
                        s.has_facial_recognition,
                        s.facial_recognition_data
                    FROM students s
                """
                updated_at_index = 18
            else:
                base_select = """
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
                        s.updated_at,
                        s.has_facial_recognition,
                        s.facial_recognition_data
                    FROM students s
                """
                updated_at_index = 17

            if full:
                # Full sync: get all students
                cloud_cur.execute(base_select + " ORDER BY s.updated_at DESC")
            else:
                # Incremental sync: only get updated students
                if self.last_student_sync:
                    cloud_cur.execute(
                        base_select + " WHERE s.updated_at > %s ORDER BY s.updated_at DESC",
                        (self.last_student_sync,),
                    )
                else:
                    # No previous sync timestamp, sync all (but still incremental mode)
                    cloud_cur.execute(base_select + " ORDER BY s.updated_at DESC")
            
            students = cloud_cur.fetchall()
            if not students:
                local_cur.execute("DELETE FROM students")
                local_conn.commit()
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
                local_cur.execute("""
                    INSERT INTO students (
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
                    ON CONFLICT (id) DO UPDATE SET
                        student_no = EXCLUDED.student_no,
                        fullname = EXCLUDED.fullname,
                        program_id = EXCLUDED.program_id,
                        year_section_id = EXCLUDED.year_section_id,
                        status = EXCLUDED.status,
                        dob = EXCLUDED.dob,
                        gender = EXCLUDED.gender,
                        email = EXCLUDED.email,
                        contact = EXCLUDED.contact,
                        address = EXCLUDED.address,
                        guardian_name = EXCLUDED.guardian_name,
                        guardian_contact = EXCLUDED.guardian_contact,
                        guardian_email = EXCLUDED.guardian_email,
                        guardian_address = EXCLUDED.guardian_address,
                        username = EXCLUDED.username,
                        password = EXCLUDED.password,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        has_facial_recognition = EXCLUDED.has_facial_recognition,
                        facial_recognition_data = EXCLUDED.facial_recognition_data
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
                local_cur.execute("""
                    INSERT INTO students (
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
                    ON CONFLICT (student_no) DO UPDATE SET
                        fullname = EXCLUDED.fullname,
                        program_id = EXCLUDED.program_id,
                        year_section_id = EXCLUDED.year_section_id,
                        status = EXCLUDED.status,
                        dob = EXCLUDED.dob,
                        gender = EXCLUDED.gender,
                        email = EXCLUDED.email,
                        contact = EXCLUDED.contact,
                        address = EXCLUDED.address,
                        guardian_name = EXCLUDED.guardian_name,
                        guardian_contact = EXCLUDED.guardian_contact,
                        guardian_email = EXCLUDED.guardian_email,
                        guardian_address = EXCLUDED.guardian_address,
                        username = EXCLUDED.username,
                        password = EXCLUDED.password,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        has_facial_recognition = EXCLUDED.has_facial_recognition,
                        facial_recognition_data = EXCLUDED.facial_recognition_data
                """)
            # Targeted delete: remove local students not in cloud (archived/removed)
            cloud_cur.execute("SELECT student_no FROM students")
            cloud_nos = [row[0] for row in cloud_cur.fetchall()]
            if cloud_nos:
                local_cur.execute(
                    "DELETE FROM students WHERE (student_no IS NULL OR NOT (student_no = ANY(%s)))",
                    (cloud_nos,),
                )
            else:
                local_cur.execute("DELETE FROM students")
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
        
        try:
            # Detect whether cloud schema has an updated_at column on fingerprints.
            # Older cloud schemas may not have it; in that case we synthesize
            # a timestamp and ensure the local table has an updated_at column.
            has_updated_at = getattr(self, "_fingerprints_has_updated_at", None)
            if has_updated_at is None:
                cloud_cur.execute("""
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_name = 'fingerprints' AND column_name = 'updated_at'
                """)
                has_updated_at = cloud_cur.fetchone()[0] > 0
                self._fingerprints_has_updated_at = has_updated_at

            if has_updated_at:
                if full:
                    cloud_cur.execute("""
                        SELECT student_no, template, updated_at
                        FROM fingerprints
                        ORDER BY updated_at DESC
                    """)
                else:
                    if self.last_fingerprint_sync:
                        cloud_cur.execute("""
                            SELECT student_no, template, updated_at
                            FROM fingerprints
                            WHERE updated_at > %s
                            ORDER BY updated_at DESC
                        """, (self.last_fingerprint_sync,))
                    else:
                        # No previous sync timestamp, sync all (but still incremental mode)
                        cloud_cur.execute("""
                            SELECT student_no, template, updated_at
                            FROM fingerprints
                            ORDER BY updated_at DESC
                        """)
            else:
                # Cloud fingerprints table has no updated_at column.
                # We synthesize a timestamp so local side can still
                # use updated_at for ordering and conflict resolution.
                if full or not self.last_fingerprint_sync:
                    cloud_cur.execute("""
                        SELECT student_no,
                               template,
                               NOW() AS updated_at
                        FROM fingerprints
                        ORDER BY student_no
                    """)
                else:
                    # Without updated_at in cloud, incremental filtering
                    # is not possible; fall back to full set.
                    cloud_cur.execute("""
                        SELECT student_no,
                               template,
                               NOW() AS updated_at
                        FROM fingerprints
                        ORDER BY student_no
                    """)
            
            fingerprints = cloud_cur.fetchall()
            if not fingerprints:
                local_cur.execute("DELETE FROM fingerprints")
                local_conn.commit()
                return

            # Ensure local fingerprints table has the expected updated_at column
            try:
                local_cur.execute("""
                    ALTER TABLE IF EXISTS fingerprints
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP
                """)
            except Exception:
                # Non-fatal; if this fails, the subsequent INSERT will report the issue
                pass
            
            # Batch upsert fingerprints
            for student_no, template, updated_at in fingerprints:
                local_cur.execute("""
                    INSERT INTO fingerprints (student_no, template, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (student_no) DO UPDATE SET
                        template = EXCLUDED.template,
                        updated_at = EXCLUDED.updated_at
                """, (student_no, Binary(template), updated_at))
            # Targeted delete: remove local fingerprints not in cloud (archived/removed)
            cloud_cur.execute("SELECT student_no FROM fingerprints")
            cloud_nos = [row[0] for row in cloud_cur.fetchall()]
            if cloud_nos:
                local_cur.execute(
                    "DELETE FROM fingerprints WHERE (student_no IS NULL OR NOT (student_no = ANY(%s)))",
                    (cloud_nos,),
                )
            else:
                local_cur.execute("DELETE FROM fingerprints")
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
        
        try:
            if full:
                cloud_cur.execute("""
                    SELECT student_no, facial_recognition_data, has_facial_recognition, updated_at
                    FROM students
                    WHERE has_facial_recognition = TRUE
                    ORDER BY updated_at DESC
                """)
            else:
                if self.last_facial_sync:
                    cloud_cur.execute("""
                        SELECT student_no, facial_recognition_data, has_facial_recognition, updated_at
                        FROM students
                        WHERE has_facial_recognition = TRUE AND updated_at > %s
                        ORDER BY updated_at DESC
                    """, (self.last_facial_sync,))
                else:
                    # No previous sync timestamp, sync all (but still incremental mode)
                    cloud_cur.execute("""
                        SELECT student_no, facial_recognition_data, has_facial_recognition, updated_at
                        FROM students
                        WHERE has_facial_recognition = TRUE
                        ORDER BY updated_at DESC
                    """)
            
            facial_data = cloud_cur.fetchall()
            if not facial_data:
                local_cur.execute(
                    """UPDATE students
                       SET has_facial_recognition = FALSE, facial_recognition_data = NULL
                       WHERE has_facial_recognition = TRUE"""
                )
                local_conn.commit()
                return

            # Full sync: clear all local facial data first, then set only those in cloud
            if full:
                local_cur.execute(
                    """UPDATE students
                       SET has_facial_recognition = FALSE, facial_recognition_data = NULL
                       WHERE has_facial_recognition = TRUE"""
                )

            # Batch update facial data
            for student_no, facial_data_blob, has_facial, updated_at in facial_data:
                local_cur.execute("""
                    UPDATE students
                    SET facial_recognition_data = %s,
                        has_facial_recognition = %s,
                        updated_at = %s
                    WHERE student_no = %s
                """, (Binary(facial_data_blob) if facial_data_blob else None, 
                      has_facial, updated_at, student_no))
            # Clear facial data on local students that no longer have it in cloud (incremental only)
            if not full:
                cloud_cur.execute(
                    "SELECT student_no FROM students WHERE has_facial_recognition = TRUE"
                )
                cloud_facial_nos = [row[0] for row in cloud_cur.fetchall()]
                if cloud_facial_nos:
                    local_cur.execute(
                        """UPDATE students
                           SET has_facial_recognition = FALSE, facial_recognition_data = NULL
                           WHERE has_facial_recognition = TRUE
                             AND (student_no IS NULL OR NOT (student_no = ANY(%s)))""",
                        (cloud_facial_nos,),
                    )
                else:
                    local_cur.execute(
                        """UPDATE students
                           SET has_facial_recognition = FALSE, facial_recognition_data = NULL
                           WHERE has_facial_recognition = TRUE"""
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
        except Exception:
            # Silent failure - no logging
            pass
    
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
                    except Exception:
                        # Silent failure - no logging
                        pass
            
        except Exception:
            # Silent failure - no logging
            pass
    
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
                # Silent failure - no logging
                failed += 1
                if operation.get('retry_count', 0) < 5:
                    operation['retry_count'] = operation.get('retry_count', 0) + 1
                    self.sync_queue.queue.put(operation)
                else:
                    # Max retries reached - save to persistent storage
                    if 'data' in operation:
                        self._save_failed_upload(operation['data'])
        
    
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
                        exit_method     = NULL,
                        exit_timestamp  = NULL,
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
            # Silent failure - no logging
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
