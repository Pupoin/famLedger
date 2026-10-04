"""Connection encoding shared by the PostgreSQL backup and container setup."""
import pytest
from sqlalchemy.engine import URL, make_url

from services.postgres_tools import pg_dump_connection


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg"])
@pytest.mark.parametrize("query_password", [False, True])
def test_pg_dump_url_uses_libpq_and_keeps_password_off_argv(driver, query_password):
    password = "test:@/密码?#&"
    query = {"sslmode": "require"}
    if query_password:
        query["password"] = password
    original = URL.create(driver, username="test-user", password=None if query_password else password,
                          host="127.0.0.1", port=5432, database="test-db", query=query)
    connection, environment = pg_dump_connection(original)
    decoded = make_url(connection)
    assert decoded.drivername == "postgresql"
    assert decoded.password is None and password not in connection
    assert "password" not in decoded.query
    assert decoded.username == "test-user" and decoded.database == "test-db"
    assert decoded.query["sslmode"] == "require"
    assert environment["PGPASSWORD"] == password


def test_pg_dump_rejects_non_postgres_url():
    with pytest.raises(ValueError):
        pg_dump_connection("sqlite:///:memory:")
