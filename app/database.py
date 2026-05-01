import sqlite3

from app.config import DATABASE_PATH

# Columns added after the initial schema. Each entry is (column_name, DDL fragment).
# The migration function checks existence before issuing ALTER TABLE so the app
# can start safely against both a fresh database and a pre-existing one.
_SARCINI_MIGRATIONS: list[tuple[str, str]] = [
    ("prioritate", "TEXT NOT NULL DEFAULT 'medie'"),
    ("data_limita", "TEXT DEFAULT NULL"),
    ("categorie", "TEXT DEFAULT NULL"),
]


def _apply_sarcini_migrations(cur: sqlite3.Cursor) -> None:
    """Add new columns to the sarcini table when they do not yet exist."""
    cur.execute("PRAGMA table_info(sarcini)")
    existing_columns = {row[1] for row in cur.fetchall()}

    for column_name, column_def in _SARCINI_MIGRATIONS:
        if column_name not in existing_columns:
            cur.execute(
                f"ALTER TABLE sarcini ADD COLUMN {column_name} {column_def}"
            )


def init_db():
    con = sqlite3.connect(DATABASE_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS utilizatori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nume TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            parola_hash TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sarcini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titlu TEXT NOT NULL,
            descriere TEXT DEFAULT '',
            finalizata INTEGER DEFAULT 0,
            data_crearii TEXT NOT NULL,
            utilizator_id INTEGER NOT NULL,
            FOREIGN KEY (utilizator_id) REFERENCES utilizatori(id)
        )
    """)
    _apply_sarcini_migrations(cur)
    con.commit()
    con.close()


def get_db():
    con = sqlite3.connect(DATABASE_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()