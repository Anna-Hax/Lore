"""Offline library delivery scenarios; not gateway or chain integration tests."""

import random
import re

import pytest

from lore_shared.leak import best_match
from lore_shared.watermark import FRAME, ONE, ZERO, score, validate_plaintext, watermark

SECRET = bytes(range(32))
VOTER = "0x" + "ab" * 20
BUYER = "0x" + "cd" * 20
TEXT = "Intro. First finding. Second finding! Third finding? Conclusion."


def visible(text):
    return text.translate(str.maketrans("", "", FRAME + ZERO + ONE))


def test_submission_and_node_marks_are_domain_separated():
    vote_copy = watermark(TEXT, VOTER, "sub:5", wm_secret=SECRET)
    node_copy = watermark(TEXT, VOTER, "node:5", wm_secret=SECRET)
    assert vote_copy != node_copy
    assert visible(vote_copy) == visible(node_copy) == TEXT
    assert score(vote_copy, VOTER, "sub:5", wm_secret=SECRET) == 10_000
    assert score(vote_copy, VOTER, "node:5", wm_secret=SECRET) < 10_000
    assert best_match(vote_copy, [(VOTER, "node:5")], wm_secret=SECRET) == (None, None, 0)


def test_vote_excerpt_with_fifty_decoys_and_buyer_copies():
    vote_copy = watermark(TEXT, VOTER, "sub:5", wm_secret=SECRET)
    excerpt = vote_copy[vote_copy.index("First"):vote_copy.index("Conclusion")]
    candidates = [(f"0x{i:040x}", "node:5" if i % 2 else "sub:5") for i in range(1, 51)]
    # The same wallet can also buy the accepted node; the original vote ref wins.
    candidates += [(VOTER, "node:5"), (BUYER, "node:5"), (VOTER, "sub:5")]
    assert best_match(excerpt, candidates, wm_secret=SECRET) == (VOTER, "sub:5", 10_000)
    assert best_match(excerpt, reversed(candidates), wm_secret=SECRET) == (VOTER, "sub:5", 10_000)


def test_submission_copy_remains_traceable_without_any_node_delivery():
    # A rejected/pending submission has no accepted node. Retain its delivery ref.
    excerpt = watermark("First. Second. Third.", VOTER, "sub:8", wm_secret=SECRET)
    assert best_match(excerpt, [(VOTER, "sub:8")], wm_secret=SECRET) == (VOTER, "sub:8", 10_000)


def test_duplicate_deliveries_do_not_change_ranking():
    copy = watermark(TEXT, VOTER, "sub:5", wm_secret=SECRET)
    candidates = [(BUYER, "node:5"), (VOTER, "sub:5")]
    assert best_match(copy, candidates * 3, wm_secret=SECRET) == best_match(copy, candidates, wm_secret=SECRET)


def test_tie_between_refs_for_same_wallet_is_order_independent():
    text = watermark("First.", VOTER, "sub:5", wm_secret=SECRET) + watermark("Second.", VOTER, "node:5", wm_secret=SECRET)
    candidates = [(VOTER, "sub:5"), (VOTER, "node:5")]
    assert best_match(text, candidates, wm_secret=SECRET) == best_match(text, reversed(candidates), wm_secret=SECRET)
    assert best_match(text, candidates, wm_secret=SECRET)[:2] == (VOTER, "node:5")


def test_one_thousand_fabricated_marks_never_name_a_candidate():
    random_source = random.Random(20261106)
    candidates = [(f"0x{i:040x}", "sub:5" if i % 2 else "node:5") for i in range(1, 51)]
    for _ in range(1000):
        fake = FRAME + "".join(random_source.choice((ZERO, ONE)) for _ in range(64)) + FRAME
        assert best_match(fake, candidates, wm_secret=SECRET) == (None, None, 0)


def test_real_mark_from_missing_wallet_never_accuses_a_decoy():
    copy = watermark(TEXT, VOTER, "sub:5", wm_secret=SECRET)
    candidates = [(f"0x{i:040x}", "sub:5") for i in range(1, 51)]
    assert best_match(copy, candidates, wm_secret=SECRET) == (None, None, 0)


def test_mixed_nodes_match_a_real_delivery_without_a_score_threshold():
    text = watermark("First node.", VOTER, "node:1", wm_secret=SECRET) + watermark("Second node.", VOTER, "node:2", wm_secret=SECRET)
    candidates = [(VOTER, "node:1"), (VOTER, "node:2"), (BUYER, "node:1")]
    wallet, ref, value = best_match(text, candidates, wm_secret=SECRET)
    assert wallet == VOTER and ref in {"node:1", "node:2"}
    assert 0 < value < 10_000
    assert value == score(text, wallet, ref, wm_secret=SECRET)


def test_junk_marks_in_leak_do_not_outvote_the_exact_mark():
    random_source = random.Random(42)
    junk = "".join(FRAME + "".join(random_source.choice((ZERO, ONE)) for _ in range(64)) + FRAME for _ in range(100))
    copy = watermark("Actual delivery.", VOTER, "sub:5", wm_secret=SECRET)
    candidates = [(f"0x{i:040x}", "sub:5") for i in range(1, 51)] + [(VOTER, "sub:5")]
    assert best_match(junk + copy, candidates, wm_secret=SECRET)[:2] == (VOTER, "sub:5")


def test_bit_similarity_without_an_exact_mark_is_not_attribution():
    copy = watermark("Only sentence.", VOTER, "sub:5", wm_secret=SECRET)
    index = copy.index(FRAME) + 1
    tampered = copy[:index] + (ONE if copy[index] == ZERO else ZERO) + copy[index + 1:]
    assert score(tampered, VOTER, "sub:5", wm_secret=SECRET) == 9843
    assert best_match(tampered, [(VOTER, "sub:5")], wm_secret=SECRET) == (None, None, 0)


def test_exact_match_is_not_discarded_when_aggregate_score_rounds_to_zero():
    copy = watermark("Only sentence.", VOTER, "sub:5", wm_secret=SECRET)
    payload = copy.split(FRAME)[1]
    opposite = payload.translate(str.maketrans({ZERO: ONE, ONE: ZERO}))
    excerpt = copy + (FRAME + opposite + FRAME) * 10_000
    assert score(excerpt, VOTER, "sub:5", wm_secret=SECRET) == 0
    assert best_match(excerpt, [(VOTER, "sub:5")], wm_secret=SECRET) == (VOTER, "sub:5", 0)


def test_chinese_sentences_without_spaces():
    text = "引言。第一项研究。第二项发现！第三项结论？后续。"
    copy = watermark(text, VOTER, "sub:5", wm_secret=SECRET)
    assert visible(copy) == text
    assert copy.count(FRAME) == 10
    excerpt = copy[copy.index("第一"):copy.index("后续")]
    assert best_match(excerpt, [(BUYER, "node:5"), (VOTER, "sub:5")], wm_secret=SECRET) == (VOTER, "sub:5", 10_000)


def test_markdown_bullets_without_sentence_punctuation():
    text = "# Report\n\n- first finding\n- second finding\n- third finding\n\n## Conclusion\nDone"
    copy = watermark(text, VOTER, "sub:5", wm_secret=SECRET)
    assert visible(copy) == text
    excerpt = copy[copy.index("- first"):copy.index("## Conclusion")]
    assert excerpt.count(FRAME) == 6
    assert best_match(excerpt, [(VOTER, "sub:5")], wm_secret=SECRET) == (VOTER, "sub:5", 10_000)


@pytest.mark.parametrize("fence", ["```", "~~~~", "````"])
def test_fenced_code_is_unchanged_and_can_be_compiled(fence):
    code = 'print("one. two.")\n# Another sentence. Still code.\n'
    text = f"Before.\n{fence}python\n{code}{fence}\nAfter."
    copy = watermark(text, VOTER, "sub:5", wm_secret=SECRET)
    extracted = copy.split(fence + "python\n", 1)[1].split(fence, 1)[0]
    assert extracted == code
    compile(extracted, "example", "exec")
    assert visible(copy) == text
    assert best_match(copy, [(VOTER, "sub:5")], wm_secret=SECRET) == (VOTER, "sub:5", 10_000)


def test_inline_code_and_unclosed_fences_are_protected():
    text = 'Use `print("one. two.")` here.\n```python\nprint("unclosed. fence.")'
    copy = watermark(text, VOTER, "sub:5", wm_secret=SECRET)
    assert re.search(r"`([^`]+)`", copy)[1] == 'print("one. two.")'
    assert copy.split("```python\n")[1] == 'print("unclosed. fence.")'
    assert visible(copy) == text


@pytest.mark.parametrize("reserved", [ZERO, ONE, FRAME])
def test_existing_invisible_characters_are_rejected(reserved):
    for function in (validate_plaintext, lambda text: watermark(text, VOTER, "sub:5", wm_secret=SECRET)):
        with pytest.raises(ValueError, match="reserved watermark"):
            function("original" + reserved + "text")


def test_watermarked_copies_cannot_be_redelivered_as_new_plaintext():
    old_copy = watermark(TEXT, BUYER, "node:1", wm_secret=SECRET)
    with pytest.raises(ValueError, match="reserved watermark"):
        watermark(old_copy, VOTER, "sub:5", wm_secret=SECRET)


def test_lone_surrogates_raise_a_sanitized_client_error():
    with pytest.raises(ValueError, match="valid UTF-8") as error:
        validate_plaintext("private content \ud800")
    assert "private content" not in str(error.value)


@pytest.mark.parametrize("kind", ["sub", "node"])
def test_maximum_uint256_ref(kind):
    ref = f"{kind}:{2**256 - 1}"
    copy = watermark(TEXT, VOTER, ref, wm_secret=SECRET)
    assert score(copy, VOTER, ref, wm_secret=SECRET) == 10_000
