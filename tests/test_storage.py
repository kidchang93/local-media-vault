from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException

from app.storage import (
    build_family_storage_path,
    build_user_storage_path,
    normalize_relative_folder,
    prune_empty_directories,
    render_template,
    resolve_inside,
    sanitize_filename,
)


class StoragePathTests(unittest.TestCase):
    def test_normalize_relative_folder_blocks_parent_references(self) -> None:
        with self.assertRaises(HTTPException):
            normalize_relative_folder("../outside")

    def test_normalize_relative_folder_sanitizes_each_part(self) -> None:
        self.assertEqual(
            normalize_relative_folder("  여행/원본:사진  "),
            "여행/원본_사진",
        )

    def test_build_user_storage_path_keeps_upload_under_user_root(self) -> None:
        rendered = render_template(
            "{year}/{month}/{original_name}",
            user="lck",
            device="iphone",
            folder="trips/seoul",
            media_type="image",
            original_name="../../IMG 0001.HEIC",
        )

        self.assertRegex(rendered, r"^\d{4}/\d{2}/IMG 0001\.HEIC$")
        self.assertEqual(
            build_user_storage_path(
                "lck",
                "trips/seoul",
                rendered,
                "{year}/{month}/{original_name}",
            ),
            f"lck/trips/seoul/{rendered}",
        )

    def test_build_family_storage_path_requires_folder(self) -> None:
        with self.assertRaises(HTTPException):
            build_family_storage_path("", "IMG_0001.HEIC", "image")

    def test_build_family_storage_path_uses_common_album_date_layout(self) -> None:
        rendered = build_family_storage_path("travel/jeju", "IMG_0001.HEIC", "image")

        self.assertRegex(
            rendered,
            r"^family/travel/jeju/\d{4}-\d{2}-\d{2}/[0-9a-f]{32}-IMG_0001\.HEIC$",
        )

    def test_template_with_folder_token_does_not_duplicate_folder(self) -> None:
        rendered = render_template(
            "{folder}/{uuid}-{original_name}",
            user="lck",
            device="iphone",
            folder="trips/seoul",
            media_type="image",
            original_name="IMG_0001.HEIC",
        )

        self.assertEqual(
            build_user_storage_path(
                "lck",
                "trips/seoul",
                rendered,
                "{folder}/{uuid}-{original_name}",
            ).count("trips/seoul"),
            1,
        )

    def test_unknown_template_token_is_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            render_template(
                "{year}/{unknown}/{original_name}",
                user="lck",
                device="iphone",
                folder="",
                media_type="image",
                original_name="IMG_0001.HEIC",
            )

    def test_resolve_inside_rejects_paths_outside_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()

            with self.assertRaises(HTTPException):
                resolve_inside(root, "../outside")

    def test_sanitize_filename_removes_path_segments(self) -> None:
        self.assertEqual(sanitize_filename("../../IMG:0001.HEIC"), "IMG_0001.HEIC")

    def test_prune_empty_directories_keeps_non_empty_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "family"
            empty = root / "album" / "2026-06-27"
            non_empty = root / "keep"
            empty.mkdir(parents=True)
            non_empty.mkdir(parents=True)
            (non_empty / "IMG_0001.JPG").write_text("photo", encoding="utf-8")

            prune_empty_directories(root)

            self.assertFalse((root / "album").exists())
            self.assertTrue(non_empty.exists())


if __name__ == "__main__":
    unittest.main()
