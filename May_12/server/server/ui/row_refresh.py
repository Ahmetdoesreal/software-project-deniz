"""Small helpers for stable dashboard row refreshes.

The dashboard receives frequent state updates. These helpers separate row
identity/order changes from cell-content changes so UI backends can update
existing rows in place instead of deleting and re-inserting every refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RowSnapshot:
    keys: tuple[str, ...]
    values: tuple[tuple[str, ...], ...]


def normalize_cell(value) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_values(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(normalize_cell(value) for value in values)


def row_snapshot(rows: Iterable[tuple[str, Sequence[object]]]) -> RowSnapshot:
    keys: list[str] = []
    values: list[tuple[str, ...]] = []
    for key, row_values in rows:
        keys.append(str(key))
        values.append(normalize_values(row_values))
    return RowSnapshot(tuple(keys), tuple(values))


def same_row_order(previous: RowSnapshot | None, current: RowSnapshot) -> bool:
    return previous is not None and previous.keys == current.keys


def same_row_key_set(previous: RowSnapshot | None, current: RowSnapshot) -> bool:
    return previous is not None and set(previous.keys) == set(current.keys)


def changed_row_indexes(previous: RowSnapshot | None, current: RowSnapshot) -> tuple[int, ...]:
    if previous is None or previous.keys != current.keys:
        return tuple(range(len(current.keys)))
    return tuple(
        index
        for index, values in enumerate(current.values)
        if previous.values[index] != values
    )


def reorder_rows_by_previous_keys(
    rows: Sequence[tuple[str, Sequence[object]]],
    previous: RowSnapshot | None,
) -> list[tuple[str, Sequence[object]]]:
    if previous is None:
        return list(rows)
    by_key = {str(key): (str(key), values) for key, values in rows}
    if set(by_key) != set(previous.keys):
        return list(rows)
    return [by_key[key] for key in previous.keys]
