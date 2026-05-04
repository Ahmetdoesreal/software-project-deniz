import unittest

from server.main import _duplicate_check_timeout


class ServerMainTests(unittest.TestCase):
    def test_duplicate_check_timeout_has_five_second_floor(self):
        self.assertEqual(_duplicate_check_timeout(1.0), 5.0)
        self.assertEqual(_duplicate_check_timeout(2.0), 5.0)

    def test_duplicate_check_timeout_scales_with_announce_interval(self):
        self.assertEqual(_duplicate_check_timeout(3.0), 7.0)
        self.assertEqual(_duplicate_check_timeout(10.0), 21.0)


if __name__ == "__main__":
    unittest.main()
