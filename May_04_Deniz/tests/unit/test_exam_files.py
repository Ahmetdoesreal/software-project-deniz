import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from client.exam import extract_exam_materials


class ExamFileExtractionTests(unittest.TestCase):
    def test_extracts_to_dated_desktop_exam_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "Desktop"
            zip_path = Path(tmp) / "materials.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("assignment/readme.txt", "hello")

            old = os.environ.get("EXAM_DESKTOP_ROOT")
            os.environ["EXAM_DESKTOP_ROOT"] = str(desktop)
            try:
                result = extract_exam_materials(zip_path, now=datetime(2026, 5, 11))
            finally:
                if old is None:
                    os.environ.pop("EXAM_DESKTOP_ROOT", None)
                else:
                    os.environ["EXAM_DESKTOP_ROOT"] = old

            extracted = Path(result["extracted_dir"])
            self.assertEqual(extracted.name, "11-05-2026")
            self.assertTrue((extracted / "assignment" / "readme.txt").is_file())

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "Desktop"
            zip_path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")

            old = os.environ.get("EXAM_DESKTOP_ROOT")
            os.environ["EXAM_DESKTOP_ROOT"] = str(desktop)
            try:
                with self.assertRaises(ValueError):
                    extract_exam_materials(zip_path, now=datetime(2026, 5, 11))
            finally:
                if old is None:
                    os.environ.pop("EXAM_DESKTOP_ROOT", None)
                else:
                    os.environ["EXAM_DESKTOP_ROOT"] = old


if __name__ == "__main__":
    unittest.main()
