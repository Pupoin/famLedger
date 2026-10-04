"""Database locks shared by workers; callers own commit/rollback."""
from sqlalchemy import text


def lock_mutation(session):
    connection = session.connection()
    if connection.dialect.name == "postgresql":
        # The same transaction lock covers membership and financial mutations.
        # This deliberately trades write parallelism for a fixed lock order.
        connection.execute(text("SELECT pg_advisory_xact_lock(734619208)"))
    elif connection.dialect.name == "sqlite":
        driver = connection.connection.driver_connection
        if not driver.in_transaction:
            connection.execute(text("BEGIN IMMEDIATE"))
