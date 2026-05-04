import unittest
from types import SimpleNamespace
from unittest.mock import patch

import setup


class SetupTests(unittest.TestCase):
    def test_run_handles_non_captured_output(self):
        completed = SimpleNamespace(returncode=0, stdout=None)
        with patch("setup.subprocess.run", return_value=completed) as run_mock:
            ok, output = setup.run(["python3", "-m", "pip", "install", "cryptography"], capture=False)

        self.assertTrue(ok)
        self.assertEqual(output, "")
        run_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
