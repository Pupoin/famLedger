"""Fail before producing a backup when pg_dump is older than its server."""
import os
import re
import subprocess
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url


def pg_dump_connection(database_url):
    """Return a libpq URL and environment without putting passwords on argv."""
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("pg_dump requires a PostgreSQL URL")
    query = dict(parsed.query)
    password = query.pop("password", parsed.password)
    connection = URL.create("postgresql", username=parsed.username, host=parsed.host,
                            port=parsed.port, database=parsed.database, query=query)
    environment = dict(os.environ)
    if password is not None:
        environment["PGPASSWORD"] = password
    return connection.render_as_string(hide_password=False), environment


def check_pg_dump_version(executable, engine):
    result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
    match = re.search(r"PostgreSQL\)\s+(\d+)", result.stdout or "")
    if result.returncode or not match:
        raise RuntimeError("Cannot determine pg_dump version")
    with engine.connect() as connection:
        server = int(connection.execute(text("SHOW server_version_num")).scalar()) // 10000
    if int(match[1]) < server:
        raise RuntimeError(f"pg_dump {match[1]} cannot back up PostgreSQL {server}")
