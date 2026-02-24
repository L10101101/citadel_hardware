import shutil


def check_postgresql_installed() -> tuple[bool, str]:
    pg_dump = shutil.which("pg_dump")
    psql = shutil.which("psql")
    if not pg_dump or not psql:
        return (
            False,
            "PostgreSQL is required but not found.\n\n"
            "Please install PostgreSQL and ensure its bin directory is in your system PATH.\n"
            "Download from: https://www.postgresql.org/download/"
        )
    return True, ""