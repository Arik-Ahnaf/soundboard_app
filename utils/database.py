import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database.db"


def initiate_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS "Sounds" (
                "ID"	INTEGER NOT NULL,
                "Title"	TEXT NOT NULL,
                "Duration"	INTEGER NOT NULL,
                "Path"	TEXT,
                PRIMARY KEY("ID" AUTOINCREMENT)
            )
        """)
        conn.commit()
    finally:
        conn.close()


def add_sound(title: str, duration: int, path: str):
    """Inserts a new sound record into the Sounds table."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO "Sounds" ("Title", "Duration", "Path") VALUES (?, ?, ?)',
            (title, duration, path)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def remove_sound(title: str):
    """Removes a sound record from the Sounds table by title."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM "Sounds" WHERE "Title" = ?',
            (title,)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_all_sounds() -> list[dict]:
    """Reads all sound records from the Sounds table."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT "ID", "Title", "Duration", "Path" FROM "Sounds"')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def rename_sound(old_title: str, new_title: str) -> str:
    """Renames a sound's title. If new_title already exists, appends '_(1)'.

    Returns the title that was actually applied.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()

        cursor.execute('SELECT 1 FROM "Sounds" WHERE "Title" = ?', (new_title,))
        if cursor.fetchone():
            new_title = f"{new_title}_(1)"

        cursor.execute(
            'UPDATE "Sounds" SET "Title" = ? WHERE "Title" = ?',
            (new_title, old_title)
        )
        conn.commit()
        return new_title
    finally:
        conn.close()