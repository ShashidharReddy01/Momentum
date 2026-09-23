from __future__ import annotations

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from momentum.core.ordering import OrderingError, key_between, keys_between


def test_basic_between() -> None:
    first = key_between(None, None)
    after = key_between(first, None)
    before = key_between(None, first)
    mid = key_between(before, first)
    assert before < mid < first < after


def test_rejects_bad_input() -> None:
    with pytest.raises(OrderingError):
        key_between("b", "a")
    with pytest.raises(OrderingError):
        key_between("a0", None)


def test_concurrent_inserts_between_same_neighbors_are_distinct() -> None:
    a, b = key_between(None, None), None
    b = key_between(a, None)
    keys = {key_between(a, b) for _ in range(200)}
    assert len(keys) > 190  # random suffix makes collisions rare
    assert all(a < k < b for k in keys)


def test_keys_between_bulk() -> None:
    ks = keys_between(None, None, 50)
    assert ks == sorted(ks) and len(set(ks)) == 50


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=120))
def test_random_insertions_keep_strict_order(positions: list[int]) -> None:
    items: list[str] = []
    for p in positions:
        i = p % (len(items) + 1)
        a = items[i - 1] if i > 0 else None
        b = items[i] if i < len(items) else None
        k = key_between(a, b)
        assert (a is None or a < k) and (b is None or k < b)
        items.insert(i, k)
    assert items == sorted(items)


def test_repeated_insert_at_front_stays_short_enough() -> None:
    b = key_between(None, None)
    for _ in range(300):
        b = key_between(None, b)
    assert len(b) < 400  # grows slowly; rebalancing handles pathological cases


def test_prefix_edge_case() -> None:
    random.seed(1)
    for _ in range(100):
        k = key_between("A", "B5")
        assert "A" < k < "B5"
