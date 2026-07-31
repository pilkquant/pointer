"""Tests for core module."""

import pytest
from tinylib.core import hash_data, serialize, process_items


def test_hash_data():
    assert hash_data("hello") == hash_data("hello")
    assert hash_data("hello") != hash_data("world")


def test_serialize():
    result = serialize({"b": 2, "a": 1})
    assert result == '{"a": 1, "b": 2}'


@pytest.fixture
def sample_items():
    return ["a", "b", "c"]


@pytest.mark.parametrize("items,expected", [
    (["a", "b"], ["A", "B"]),
    ([], []),
    (["", "x"], ["X"]),
])
def test_process_items(items, expected):
    assert process_items(items) == expected
