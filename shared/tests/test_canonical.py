import math

import pytest

from lore_shared.canonical import canonical_hash, canonical_json
from lore_shared.crypto import content_hash


def test_recursive_order_and_utf8():
    first = {"z": [{"b": 2, "a": "研究"}], "a": True}
    second = {"a": True, "z": [{"a": "研究", "b": 2}]}
    expected = '{"a":true,"z":[{"a":"研究","b":2}]}'
    assert canonical_json(first) == expected
    assert canonical_hash(first) == canonical_hash(second) == content_hash(expected)


def test_array_order_changes_hash():
    assert canonical_hash([1, 2]) != canonical_hash([2, 1])


def test_json_types_and_escaping():
    assert canonical_json([None, False, 1.25, "line\n\"quote"]) == '[null,false,1.25,"line\\n\\\"quote"]'


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, {1: "one"}, {"x": {1, 2}}, b"x", (1, 2)])
def test_reject_non_json_values(value):
    with pytest.raises(ValueError):
        canonical_json(value)
