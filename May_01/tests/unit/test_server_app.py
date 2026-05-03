import unittest
from argparse import Namespace
from unittest.mock import patch

from server.app import _duplicate_guard_timeout, _is_same_server_instance, _server_identity_hosts, _shutdown_grace_seconds


class ServerAppTests(unittest.TestCase):
    def test_duplicate_guard_timeout_has_five_second_floor(self):
        self.assertEqual(_duplicate_guard_timeout(1.0), 5.0)
        self.assertEqual(_duplicate_guard_timeout(2.0), 5.0)

    def test_duplicate_guard_timeout_scales_with_announce_interval(self):
        self.assertEqual(_duplicate_guard_timeout(3.0), 7.0)
        self.assertEqual(_duplicate_guard_timeout(10.0), 21.0)

    def test_server_identity_hosts_include_explicit_bind_host(self):
        with patch("server.app._candidate_ipv4_hosts", return_value=["192.168.1.50", "127.0.0.1"]):
            hosts = _server_identity_hosts("10.0.0.8")

        self.assertEqual(hosts, {"192.168.1.50", "127.0.0.1", "10.0.0.8"})

    def test_is_same_server_instance_matches_known_host_and_port(self):
        app = {"host": "0.0.0.0", "port": 8080}
        with patch("server.app._candidate_ipv4_hosts", return_value=["192.168.1.50", "127.0.0.1"]):
            self.assertTrue(_is_same_server_instance(app, "192.168.1.50", 8080))
            self.assertFalse(_is_same_server_instance(app, "192.168.1.51", 8080))
            self.assertFalse(_is_same_server_instance(app, "192.168.1.50", 8081))

    def test_shutdown_grace_seconds_uses_cli_value(self):
        self.assertEqual(_shutdown_grace_seconds(Namespace(shutdown_grace_seconds=12.5)), 12.5)


if __name__ == "__main__":
    unittest.main()
