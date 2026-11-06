import hashlib
import hmac

import pytest

from lore_shared.leak import best_match
from lore_shared.watermark import FRAME, ONE, ZERO, score, watermark

SECRET = bytes(range(32))
WALLET = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20
TEXT = 'First finding. Second finding! "Third finding?" Fourth finding. Last finding'


def visible(text):
    return text.translate(str.maketrans("", "", FRAME + ZERO + ONE))


def test_deterministic_wallet_and_node_specific():
    marked = watermark(TEXT, WALLET, "node:1", wm_secret=SECRET)
    assert marked == watermark(TEXT, WALLET, "node:1", wm_secret=SECRET)
    assert marked == watermark(TEXT, "0x" + "AB" * 20, "node:1", wm_secret=SECRET)
    assert marked != watermark(TEXT, OTHER, "node:1", wm_secret=SECRET)
    assert marked != watermark(TEXT, WALLET, "node:2", wm_secret=SECRET)
    assert score(marked, WALLET, "node:1", wm_secret=SECRET) == 10_000


@pytest.mark.parametrize("text", [TEXT, "", "No punctuation", "  whitespace  ", "研究。 Another!\nNext?", "Wait... Really?!"])
def test_visible_text_is_unchanged(text):
    assert visible(watermark(text, WALLET, "node:1", wm_secret=SECRET)) == text


def test_payload_encoding_and_sentence_repetition():
    marked = watermark(TEXT, WALLET, "node:1", wm_secret=SECRET)
    payload = marked.split(FRAME)[1]
    decoded = int("".join("1" if bit == ONE else "0" for bit in payload), 2).to_bytes(8, "big")
    assert decoded == hmac.new(SECRET, bytes.fromhex(WALLET[2:]) + b"node:1", hashlib.sha256).digest()[:8]
    assert marked.count(FRAME) == 10  # Five sentences, including the final unpunctuated one.


def test_three_sentence_excerpt_against_fifty_decoys():
    marked = watermark(TEXT, WALLET, "node:42", wm_secret=SECRET)
    excerpt = marked[marked.index("Second"):marked.index("Last")]
    decoys = [(f"0x{i:040x}", "node:42") for i in range(1, 51)]
    candidates = decoys + [(WALLET, "node:42")]
    assert best_match(excerpt, candidates, wm_secret=SECRET) == (WALLET, "node:42", 10_000)
    assert all(score(excerpt, candidate[0], "node:42", wm_secret=SECRET) < 10_000 for candidate in decoys)
    assert best_match(excerpt, reversed(candidates), wm_secret=SECRET) == (WALLET, "node:42", 10_000)


def test_no_marks_and_stripped_marks_never_attribute():
    candidates = [(WALLET, "node:1")]
    assert best_match(TEXT, candidates, wm_secret=SECRET) == (None, None, 0)
    assert best_match(visible(watermark(TEXT, WALLET, "node:1", wm_secret=SECRET)), candidates, wm_secret=SECRET) == (None, None, 0)
    assert best_match(TEXT, [], wm_secret=SECRET) == (None, None, 0)


def test_partial_mark_does_not_desynchronize_later_sentences():
    marked = watermark(TEXT, WALLET, "node:1", wm_secret=SECRET)
    assert score(marked[marked.index(FRAME) + 20:], WALLET, "node:1", wm_secret=SECRET) == 10_000
    assert score(FRAME + ZERO * 63 + FRAME, WALLET, "node:1", wm_secret=SECRET) == 0


def test_bit_fraction():
    marked = watermark("Only sentence.", WALLET, "node:1", wm_secret=SECRET)
    index = marked.index(FRAME) + 1
    flipped = ONE if marked[index] == ZERO else ZERO
    marked = marked[:index] + flipped + marked[index + 1:]
    assert score(marked, WALLET, "node:1", wm_secret=SECRET) == 63 * 10_000 // 64


def test_ties_are_order_independent():
    a = watermark("One.", WALLET, "node:1", wm_secret=SECRET)
    b = watermark("Two.", OTHER, "node:1", wm_secret=SECRET)
    candidates = [(WALLET, "node:1"), (OTHER, "node:1")]
    assert best_match(a + b, candidates, wm_secret=SECRET) == best_match(a + b, reversed(candidates), wm_secret=SECRET)


@pytest.mark.parametrize("ref", [0, 1, "1", "node:0", "sub:0", "node:01", "sub:05", "node:-1", "sub:1.5", "NODE:1", "node:１", " node:1", "node:1\n", f"sub:{2**256}", "other:5", True, None])
def test_invalid_refs(ref):
    with pytest.raises(ValueError):
        watermark(TEXT, WALLET, ref, wm_secret=SECRET)


def test_wallet_validation_and_missing_secret(monkeypatch):
    with pytest.raises(ValueError):
        watermark(TEXT, "not a wallet", "node:1", wm_secret=SECRET)
    monkeypatch.delenv("WM_SECRET", raising=False)
    with pytest.raises(ValueError, match="WM_SECRET"):
        watermark(TEXT, WALLET, "node:1")
    monkeypatch.setenv("WM_SECRET", SECRET.hex())
    assert watermark(TEXT, WALLET, "node:1") == watermark(TEXT, WALLET, "node:1", wm_secret=SECRET)
