from lore_shared.leak import best_match, match_evidence
from lore_shared.watermark import watermark

SECRET = bytes(range(32))
A, B, C = ("0x" + byte * 40 for byte in ("a", "b", "c"))


def copy(wallet, ref):
    return watermark("First finding. Second finding. Third finding.", wallet, ref, wm_secret=SECRET)


def test_cross_wallet_tie_is_exposed_without_changing_legacy_match():
    text = copy(A, "node:1") + copy(B, "sub:2")
    candidates = [(B, "sub:2"), (A, "node:1"), (C, "node:1")]
    evidence = match_evidence(text, candidates, wm_secret=SECRET)
    assert evidence.ambiguous
    assert evidence.tied_wallets == (A, B)
    assert (evidence.wallet, evidence.ref, evidence.score_bps) == best_match(text, candidates, wm_secret=SECRET)
    assert evidence == match_evidence(text, reversed(candidates), wm_secret=SECRET)


def test_multiple_refs_and_duplicate_rows_for_one_wallet_do_not_create_a_wallet_tie():
    text = copy(A, "node:1") + copy(A, "sub:2")
    evidence = match_evidence(text, [(A, "node:1"), (A, "sub:2"), (A, "node:1")], wm_secret=SECRET)
    assert evidence.tied_wallets == (A,)
    assert not evidence.ambiguous


def test_unmatched_evidence_does_not_name_a_wallet():
    evidence = match_evidence(copy(C, "sub:1"), [(A, "node:1")], wm_secret=SECRET)
    assert (evidence.wallet, evidence.ref, evidence.score_bps, evidence.tied_wallets) == (None, None, 0, ())


def test_unique_match():
    evidence = match_evidence(copy(B, "sub:2"), [(A, "node:1"), (B, "sub:2")], wm_secret=SECRET)
    assert (evidence.wallet, evidence.ref, evidence.score_bps, evidence.ambiguous) == (B, "sub:2", 10000, False)
