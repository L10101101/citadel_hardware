import os
import re
import subprocess
import tempfile
import logging

from typing import Sequence
from db_utils import LOCAL_DB, CLOUD_DB, get_local_connection

logger = logging.getLogger(__name__)


def local_needs_schema() -> bool:
    try:
        local_conn, _ = get_local_connection()
        cur = local_conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'students'
            """
        )
        exists = cur.fetchone()[0] > 0
        cur.close()
        local_conn.close()
        return not exists
    except Exception:
        return True


def _strip_fk_constraints_from_schema_sql(schema_path: str) -> None:
    with open(schema_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    content = re.sub(
        r"ALTER\s+TABLE\s+[^;]*?\bADD\s+CONSTRAINT\s+[^;]*?\bFOREIGN\s+KEY\s+[^;]*?;",
        "-- (FK constraint removed for local cache)\n",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    content = re.sub(
        r"\s+REFERENCES\s+\S+\s*\([^)]*\)(\s+ON\s+(DELETE|UPDATE)\s+\w+)*",
        "",
        content,
        flags=re.IGNORECASE,
    )

    content = re.sub(
        r",\s*CONSTRAINT\s+\w+\s+FOREIGN\s+KEY\s*\([^)]*\)\s+REFERENCES\s+\S+\s*\([^)]*\)(\s+ON\s+(DELETE|UPDATE)\s+\w+)*",
        "",
        content,
        flags=re.IGNORECASE,
    )

    with open(schema_path, "w", encoding="utf-8") as f:
        f.write(content)


def sync_schema_from_cloud() -> bool:
    dump_exe = "pg_dump"
    psql_exe = "psql"
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
            schema_path = f.name
    except Exception as e:
        logger.exception("Schema sync failed while creating temporary schema file: %s", e)
        return False

    try:
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
            logger.error(
                "Schema dump failed: %s",
                r.stderr[:500] if r.stderr else r.stdout[:500],
            )
            return False

        _strip_fk_constraints_from_schema_sql(schema_path)

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
        r = subprocess.run(
            cmd_psql, env=env_local, capture_output=True, text=True, timeout=120
        )
        if r.returncode != 0:
            err = (r.stderr or "") + (r.stdout or "")
            logger.warning("Schema apply warning: %s", err[:400])
        else:
            logger.info("Schema synced from cloud to local (without FK constraints)")
        return True
    except subprocess.TimeoutExpired:
        logger.warning("Schema sync timed out")
        return False
    except FileNotFoundError:
        logger.warning("pg_dump or psql not found; add PostgreSQL bin to PATH for schema sync")
        return False
    except Exception:
        logger.exception("Schema sync failed")
        return False
    finally:
        try:
            os.unlink(schema_path)
        except Exception:
            pass


def sync_full_table(cloud_cur, local_cur, table_name: str, pk_column: str = "id") -> None:
    cloud_cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    cloud_cols = [row[0] for row in cloud_cur.fetchall()]
    if not cloud_cols:
        return
    local_cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
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
            deleted = local_cur.rowcount
            if deleted:
                logger.info("Purged %d rows from %s", deleted, table_name)
        except Exception as e:
            logger.warning("Failed to purge %s: %s", table_name, e)
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
    logger.info("Synced %d rows for %s", len(rows), table_name)


def sync_reference_tables(cloud_conn, local_conn) -> None:
    cloud_cur = cloud_conn.cursor()
    local_cur = local_conn.cursor()
    ref_tables: Sequence[str] = ("programs", "year_sections")
    try:
        try:
            for table in ref_tables:
                local_cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s AND is_nullable = 'NO'
                    """,
                    (table,),
                )
                non_null_cols = [row[0] for row in local_cur.fetchall()] or []
                local_cur.execute(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = %s::regclass AND i.indisprimary
                    """,
                    (table,),
                )
                pk_cols = {row[0] for row in local_cur.fetchall()} or set()
                for col in non_null_cols:
                    if col in pk_cols:
                        continue
                    try:
                        local_cur.execute(
                            f'ALTER TABLE {table} ALTER COLUMN "{col}" DROP NOT NULL'
                        )
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Failed to relax NOT NULL constraints on reference tables: %s", e)

        for table in ref_tables:
            try:
                sync_full_table(cloud_cur, local_cur, table, "id")
            except Exception as e:
                logger.warning("Failed to sync %s: %s", table, e)

        local_conn.commit()
    except Exception as e:
        local_conn.rollback()
        logger.warning("Reference table sync failed: %s", e)
    finally:
        cloud_cur.close()
        local_cur.close()


def sync_verification_methods(cloud_conn, local_conn) -> None:
    cloud_cur = cloud_conn.cursor()
    local_cur = local_conn.cursor()
    try:
        try:
            cloud_cur.execute(
                """
                SELECT id, method
                FROM verification_methods
                ORDER BY id
                """
            )
            rows = cloud_cur.fetchall()
            if not rows:
                return
            for vid, vmethod in rows:
                local_cur.execute(
                    """
                    INSERT INTO verification_methods (id, method)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        method = EXCLUDED.method
                    """,
                    (vid, vmethod),
                )
            local_conn.commit()
        except Exception as e:
            local_conn.rollback()
            logger.warning("Failed to sync verification_methods: %s", e)
    finally:
        cloud_cur.close()
        local_cur.close()
