"""Rank known deliveries using the v1 watermark; never infer a penalty."""

from collections.abc import Iterable
from dataclasses import dataclass

from .watermark import _MARK, _payload, normalize_wallet, score


LeakCandidate = tuple[str, str]  # (wallet, "node:<id>" | "sub:<id>")


@dataclass(frozen=True)
class MatchEvidence:
    wallet: str | None
    ref: str | None
    score_bps: int
    # All distinct wallets at the top score, including the selected wallet.
    tied_wallets: tuple[str, ...]

    @property
    def ambiguous(self) -> bool:
        return len(self.tied_wallets) > 1


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
    match = match_evidence(text, candidates, wm_secret=wm_secret)
    return match.wallet, match.ref, match.score_bps


def match_evidence(
    text: str, candidates: Iterable[LeakCandidate], *, wm_secret: bytes | None = None
) -> MatchEvidence:
    """Expose wallet ties for human review without changing best_match's ABI.

    Multiple top-scoring refs for the same wallet are not a cross-wallet tie.
    Even an unambiguous high score is only evidence, never an automatic penalty.
    The gateway must persist this evidence and the match time; existing Reports
    contracts cannot enforce the proposal's tie/delay rules from best_match alone.
    """
    marks = set(_MARK.findall(text))
    winner, best = None, 0
    top_wallets: set[str] = set()
    for wallet, ref in candidates:
        candidate = (normalize_wallet(wallet), ref)
        if _payload(candidate[0], ref, wm_secret) not in marks:
            continue
        value = score(text, candidate[0], ref, wm_secret=wm_secret)
        if winner is None or value > best:
            winner, best = candidate, value
            top_wallets = {candidate[0]}
        elif value == best:
            top_wallets.add(candidate[0])
            if candidate < winner:
                winner = candidate
    return (MatchEvidence(*winner, best, tuple(sorted(top_wallets))) if winner is not None
            else MatchEvidence(None, None, 0, ()))
