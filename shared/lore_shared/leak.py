"""Rank known deliveries using the v1 watermark; never infer a penalty."""

from collections.abc import Iterable

from .watermark import _MARK, _payload, normalize_wallet, score


LeakCandidate = tuple[str, str]  # (wallet, "node:<id>" | "sub:<id>")


def best_match(
    text: str, candidates: Iterable[LeakCandidate], *, wm_secret: bytes | None = None
) -> tuple[str | None, str | None, int]:
    """Return (normalized wallet, ref, score_bps), or (None, None, 0).

    A candidate must have at least one exact complete HMAC mark in the excerpt;
    bit similarity alone must never name an unrelated wallet. The returned score
    still measures all decoded bits, so mixed-ref excerpts can score below 10000.
    Supply (wallet, ref) pairs from every user delivery in the reported topic,
    including voters' submission copies and buyers' node copies. Equal
    scores break lexicographically by (normalized wallet, ref), so database row
    order cannot change the result. Ties and nonzero scores are not attribution.
    """
    marks = set(_MARK.findall(text))
    winner, best = None, 0
    for wallet, ref in candidates:
        candidate = (normalize_wallet(wallet), ref)
        if _payload(candidate[0], ref, wm_secret) not in marks:
            continue
        value = score(text, candidate[0], ref, wm_secret=wm_secret)
        if winner is None or value > best or (value == best and candidate < winner):
            winner, best = candidate, value
    return (*winner, best) if winner is not None else (None, None, 0)
