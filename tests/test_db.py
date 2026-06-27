from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import (
    COMMON_ROOT_PREFIX,
    DEFAULT_STORAGE_TEMPLATE,
    authenticate_user,
    create_session,
    delete_session,
    get_user_by_session,
    init_db,
)


class DbAuthTests(unittest.TestCase):
    def test_init_db_creates_lck_cse_users(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "vault.sqlite3"
            init_db(
                db_path,
                {
                    "admin": "admin-pass",
                    "lck": "lck-pass",
                    "cse": "cse-pass",
                },
            )

            admin = authenticate_user(db_path, "admin", "admin-pass")
            lck = authenticate_user(db_path, "lck", "lck-pass")
            cse = authenticate_user(db_path, "cse", "cse-pass")

            self.assertIsNotNone(admin)
            self.assertIsNotNone(lck)
            self.assertIsNotNone(cse)
            self.assertEqual(lck["root_prefix"], COMMON_ROOT_PREFIX)
            self.assertEqual(cse["default_template"], DEFAULT_STORAGE_TEMPLATE)

    def test_session_lifecycle_is_db_backed(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "vault.sqlite3"
            init_db(
                db_path,
                {
                    "admin": "admin-pass",
                    "lck": "lck-pass",
                    "cse": "cse-pass",
                },
            )

            user = authenticate_user(db_path, "lck", "lck-pass")
            token = create_session(db_path, user["id"])

            self.assertEqual(get_user_by_session(db_path, token)["username"], "lck")
            delete_session(db_path, token)
            self.assertIsNone(get_user_by_session(db_path, token))


if __name__ == "__main__":
    unittest.main()
