from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from app.security import hash_password, new_session_token, verify_password


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',
  can_upload INTEGER NOT NULL DEFAULT 1,
  can_create_folder INTEGER NOT NULL DEFAULT 0,
  can_modify_folder INTEGER NOT NULL DEFAULT 0,
  can_delete INTEGER NOT NULL DEFAULT 0,
  root_prefix TEXT NOT NULL,
  default_template TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(owner_user_id, relative_path)
);

CREATE TABLE IF NOT EXISTS uploads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  original_name TEXT NOT NULL,
  stored_relative_path TEXT NOT NULL,
  media_type TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  thumbnail_relative_path TEXT,
  thumbnail_status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

DEFAULT_STORAGE_TEMPLATE = "{folder}/{date}/{uuid}-{original_name}"
COMMON_ROOT_PREFIX = "family"


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path, bootstrap_passwords: dict[str, str]) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        if row["count"]:
            return

        users = [
            {
                "username": "admin",
                "display_name": "Admin",
                "role": "admin",
                "password": bootstrap_passwords["admin"],
                "can_upload": 1,
                "can_create_folder": 1,
                "can_modify_folder": 1,
                "can_delete": 1,
                "root_prefix": COMMON_ROOT_PREFIX,
                "default_template": DEFAULT_STORAGE_TEMPLATE,
            },
            {
                "username": "lck",
                "display_name": "lck",
                "role": "user",
                "password": bootstrap_passwords["lck"],
                "can_upload": 1,
                "can_create_folder": 1,
                "can_modify_folder": 1,
                "can_delete": 0,
                "root_prefix": COMMON_ROOT_PREFIX,
                "default_template": DEFAULT_STORAGE_TEMPLATE,
            },
            {
                "username": "cse",
                "display_name": "cse",
                "role": "user",
                "password": bootstrap_passwords["cse"],
                "can_upload": 1,
                "can_create_folder": 1,
                "can_modify_folder": 1,
                "can_delete": 0,
                "root_prefix": COMMON_ROOT_PREFIX,
                "default_template": DEFAULT_STORAGE_TEMPLATE,
            },
        ]

        for user in users:
            conn.execute(
                """
                INSERT INTO users (
                  username, display_name, password_hash, role, can_upload,
                  can_create_folder, can_modify_folder, can_delete,
                  root_prefix, default_template
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["username"],
                    user["display_name"],
                    hash_password(user["password"]),
                    user["role"],
                    user["can_upload"],
                    user["can_create_folder"],
                    user["can_modify_folder"],
                    user["can_delete"],
                    user["root_prefix"],
                    user["default_template"],
                ),
            )


def authenticate_user(db_path: Path, username: str, password: str) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return None
        return user


def create_session(db_path: Path, user_id: int) -> str:
    token = new_session_token()
    with connect(db_path) as conn:
        conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    return token


def delete_session(db_path: Path, token: str) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_user_by_session(db_path: Path, token: str) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
