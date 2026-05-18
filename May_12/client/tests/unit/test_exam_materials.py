import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from client.exam import extract_exam_materials, stage_exam_materials


class ExamMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.zip_path = self.root / "exam_materials.zip"
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            archive.writestr("assignment/readme.txt", "hello")
            archive.writestr("assignment/src/main.py", "print('ok')\n")
        self.now = datetime(2026, 5, 18, 12, 0, 0)
        self.env_patch = patch.dict(os.environ, {"EXAM_DESKTOP_ROOT": str(self.root / "Desktop")})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_stage_marks_archive_pending_without_extracting(self):
        info = stage_exam_materials(self.zip_path)

        self.assertTrue(info["has_files"])
        self.assertTrue(info["pending_extraction"])
        self.assertEqual(info["extracted_dir"], "")
        self.assertFalse((self.root / "Desktop" / "Exam").exists())

    def test_extract_reuses_intact_managed_folder(self):
        first = extract_exam_materials(self.zip_path, now=self.now)
        second = extract_exam_materials(self.zip_path, now=self.now)

        folder = Path(first["extracted_dir"])
        self.assertEqual(folder.name, "18-05-2026")
        self.assertEqual(second["extracted_dir"], first["extracted_dir"])
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertTrue((folder / "assignment" / "readme.txt").exists())

    def test_force_new_uses_underscore_suffixes(self):
        first = extract_exam_materials(self.zip_path, now=self.now)
        second = extract_exam_materials(self.zip_path, now=self.now, force_new=True)
        third = extract_exam_materials(self.zip_path, now=self.now, force_new=True)

        self.assertEqual(Path(first["extracted_dir"]).name, "18-05-2026")
        self.assertEqual(Path(second["extracted_dir"]).name, "18-05-2026_2")
        self.assertEqual(Path(third["extracted_dir"]).name, "18-05-2026_3")
        self.assertFalse(second["reused"])
        self.assertFalse(third["reused"])

    def test_reset_after_deleted_files_creates_fresh_suffix_folder(self):
        first = extract_exam_materials(self.zip_path, now=self.now)
        deleted_file = Path(first["extracted_dir"]) / "assignment" / "readme.txt"
        deleted_file.unlink()

        reset = extract_exam_materials(self.zip_path, now=self.now, force_new=True)

        reset_folder = Path(reset["extracted_dir"])
        self.assertEqual(reset_folder.name, "18-05-2026_2")
        self.assertTrue((reset_folder / "assignment" / "readme.txt").exists())


if __name__ == "__main__":
    unittest.main()
