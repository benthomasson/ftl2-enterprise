from sqlalchemy import create_engine, event

from .schema import metadata


def create_db(path="loops.db"):
    """Create a SQLite database with WAL mode and all tables."""
    engine = create_engine(f"sqlite:///{path}")

    # Enable WAL mode for concurrent reads during writes
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine
