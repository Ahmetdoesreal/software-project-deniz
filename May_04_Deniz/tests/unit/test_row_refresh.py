import unittest

from server.ui.row_refresh import (
    changed_row_indexes,
    reorder_rows_by_previous_keys,
    row_snapshot,
    same_row_key_set,
    same_row_order,
)


class RowRefreshTests(unittest.TestCase):
    def test_snapshot_normalizes_keys_and_values(self):
        snapshot = row_snapshot([(1, ("Alice", 10, None)), ("2", ("Bob", 0, "x"))])

        self.assertEqual(snapshot.keys, ("1", "2"))
        self.assertEqual(snapshot.values, (("Alice", "10", ""), ("Bob", "0", "x")))

    def test_changed_row_indexes_only_reports_cell_changes_when_order_same(self):
        previous = row_snapshot([("a", ("Alice", "10")), ("b", ("Bob", "20"))])
        current = row_snapshot([("a", ("Alice", "9")), ("b", ("Bob", "20"))])

        self.assertTrue(same_row_order(previous, current))
        self.assertEqual(changed_row_indexes(previous, current), (0,))

    def test_changed_row_indexes_reports_all_rows_when_order_changes(self):
        previous = row_snapshot([("a", ("Alice",)), ("b", ("Bob",))])
        current = row_snapshot([("b", ("Bob",)), ("a", ("Alice",))])

        self.assertFalse(same_row_order(previous, current))
        self.assertEqual(changed_row_indexes(previous, current), (0, 1))

    def test_reorder_rows_by_previous_keys_preserves_visible_order_when_key_set_same(self):
        previous = row_snapshot([("a", ("Alice", "10")), ("b", ("Bob", "20"))])
        rows = [("b", ("Bob", "19")), ("a", ("Alice", "9"))]

        reordered = reorder_rows_by_previous_keys(rows, previous)

        self.assertTrue(same_row_key_set(previous, row_snapshot(reordered)))
        self.assertEqual([key for key, _values in reordered], ["a", "b"])

    def test_reorder_rows_keeps_new_order_when_key_set_changes(self):
        previous = row_snapshot([("a", ("Alice",)), ("b", ("Bob",))])
        rows = [("c", ("Cara",)), ("a", ("Alice",))]

        self.assertEqual(reorder_rows_by_previous_keys(rows, previous), rows)


if __name__ == "__main__":
    unittest.main()
