import unittest

from mytask_payload_adapter import MytaskPayloadAdapter, default_policy


class FakeMonitor:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)

    def snapshot(self):
        return self.snapshots.pop(0)


class PayloadBuilderTests(unittest.TestCase):
    def test_payload_keeps_baris_fields_and_adds_incidents(self):
        monitor = FakeMonitor(
            [
                {
                    "active_window": "Python Exam",
                    "open_processes": ["python"],
                    "processes": [{"pid": 1, "name": "python.exe", "username": "DESKTOP\\student"}],
                    "idle_seconds": 1,
                    "captured_at": 1.0,
                },
                {
                    "active_window": "Discord",
                    "open_processes": ["python", "discord"],
                    "processes": [
                        {"pid": 1, "name": "python.exe", "username": "DESKTOP\\student"},
                        {"pid": 2, "name": "discord.exe", "username": "DESKTOP\\student"},
                    ],
                    "idle_seconds": 1,
                    "captured_at": 2.0,
                },
            ]
        )
        policy = default_policy()
        policy["rules"][0]["process_usernames"] = ["student"]
        adapter = MytaskPayloadAdapter("std_01", "Test Student", policy=policy)

        first = adapter.build_from_snapshot(monitor.snapshot())
        second = adapter.build_from_snapshot(monitor.snapshot())

        for key in ["student_id", "student_name", "active_window", "open_apps", "idle_seconds", "flags"]:
            self.assertIn(key, second)
        self.assertIn("incidents", second)
        self.assertIn("processes", second)
        self.assertEqual(first["flags"], [])
        self.assertTrue(any(flag.startswith("BANNED:discord") for flag in second["flags"]))
        self.assertTrue(any(item["rule_id"] == "process_blacklist" for item in second["incidents"]))


if __name__ == "__main__":
    unittest.main()
