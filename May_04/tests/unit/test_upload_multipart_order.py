import unittest

from server.handlers import _find_file_part, _read_remaining_text_fields


class _FakePart:
    def __init__(self, name: str, value: str = "", filename: str | None = None):
        self.name = name
        self._value = value
        self.filename = filename
        self._drained = False

    async def text(self):
        return self._value

    async def read_chunk(self):
        if self._drained:
            return b""
        self._drained = True
        return b"chunk"


class _FakeReader:
    def __init__(self, parts):
        self.parts = list(parts)
        self.index = 0

    async def next(self):
        if self.index >= len(self.parts):
            return None
        part = self.parts[self.index]
        self.index += 1
        return part


class MultipartOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_find_file_part_collects_fields_before_file(self):
        reader = _FakeReader(
            [
                _FakePart("metadata", '{"source":"test"}'),
                _FakePart("sha256", "abc123"),
                _FakePart("archive", filename="bundle.zip"),
            ]
        )

        file_part, pre_fields = await _find_file_part(reader, "archive")
        self.assertIsNotNone(file_part)
        self.assertEqual(file_part.name, "archive")
        self.assertEqual(pre_fields["sha256"], "abc123")
        self.assertIn("metadata", pre_fields)

    async def test_read_remaining_text_fields_collects_fields_after_file(self):
        reader = _FakeReader(
            [
                _FakePart("sha256", "xyz"),
                _FakePart("kind", "incident_bundle"),
                _FakePart("metadata", '{"incident_id":"i-1"}'),
            ]
        )
        fields = await _read_remaining_text_fields(reader)
        self.assertEqual(fields["sha256"], "xyz")
        self.assertEqual(fields["kind"], "incident_bundle")
        self.assertIn("incident_id", fields["metadata"])


if __name__ == "__main__":
    unittest.main()
