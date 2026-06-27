from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import init_db
from app.main import app


class ApiUploadTests(unittest.TestCase):
    def test_recent_uploads_preview_and_clear_test_data(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                data_dir=root / "data",
                upload_root=root / "uploads",
                admin_password="admin-pass",
                lck_password="lck-pass",
                cse_password="cse-pass",
                app_base_url="",
            )
            app.dependency_overrides[get_settings] = lambda: settings
            init_db(
                settings.db_path,
                {
                    "admin": "admin-pass",
                    "lck": "lck-pass",
                    "cse": "cse-pass",
                },
            )

            try:
                client = TestClient(app)
                try:
                    response = client.post(
                        "/api/login",
                        data={"username": "lck", "password": "lck-pass"},
                    )
                    self.assertEqual(response.status_code, 200)

                    response = client.post("/api/folders", json={"relativePath": "test"})
                    self.assertEqual(response.status_code, 200)

                    for index in range(12):
                        response = client.post(
                            "/api/uploads",
                            data={"folder": "test"},
                            files={
                                "files": (
                                    f"IMG_{index:04d}.JPG",
                                    f"image-{index}".encode(),
                                    "image/jpeg",
                                )
                            },
                        )
                        self.assertEqual(response.status_code, 200)

                    response = client.get("/api/uploads")
                    self.assertEqual(response.status_code, 200)
                    uploads = response.json()
                    self.assertEqual(len(uploads), 10)
                    self.assertIn("/api/uploads/", uploads[0]["previewUrl"])
                    self.assertTrue(uploads[0]["previewUrl"].endswith("/preview"))
                    self.assertFalse(settings.thumbnail_root.exists())

                    response = client.get(uploads[0]["previewUrl"])
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["content-type"], "image/jpeg")

                    response = client.post("/api/test-data/clear")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["deletedUploads"], 12)
                    self.assertEqual(client.get("/api/uploads").json(), [])
                    self.assertEqual(list((settings.upload_root / "family").rglob("*")), [])
                finally:
                    client.close()
            finally:
                app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
