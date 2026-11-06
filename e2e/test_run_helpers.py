import importlib.util
from pathlib import Path

import pytest

from lore_shared.constants import MIN_CHARS
from lore_shared.leak import best_match
from lore_shared.watermark import watermark

spec = importlib.util.spec_from_file_location("e2e_run", Path(__file__).with_name("run.py"))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

SECRET = bytes(range(32))
WALLET = "0x" + "ab" * 20


def test_synthetic_research_meets_the_length_rule_and_differs_per_run():
    assert len(run.research("fees", "a")) >= MIN_CHARS
    assert run.research("fees", "a") != run.research("fees", "b")


def test_scenario_excerpt_is_traceable():
    copy = watermark(run.research("fees", "a"), WALLET, "node:1", wm_secret=SECRET)
    excerpt = run.three_sentences(copy)
    assert run.visible(copy) == run.research("fees", "a")
    assert best_match(excerpt, [(WALLET, "node:1")], wm_secret=SECRET) == (WALLET, "node:1", 10_000)


def test_excerpt_refuses_an_unmarked_copy():
    with pytest.raises(AssertionError):
        run.three_sentences(run.research("fees", "a"))
