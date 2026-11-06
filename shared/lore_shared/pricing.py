"""Integer reference calculations for the dynamic pricing proposal.

These do not replace on-chain priceOf/access checks or authorize transactions.
No floats, RPCs, model calls or state persistence are used here.
"""

from dataclasses import dataclass
from math import isqrt

from .constants import PricingParameters

BPS = 10_000
DEFAULTS = PricingParameters()


def _uint(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value < 2**256:
        raise ValueError(f"{name} must be a uint256 integer >= {minimum}")


def topic_price(p0: int, nodes: int, buyers30d: int, *, params=DEFAULTS) -> int:
    """Price before counting this purchase, capped then floored to the tick.

    sqrt(buyers * 1e8) retains four decimals. Keep that precision through the
    multiplication; do not truncate the demand factor to whole bps first.
    Python intermediates are unbounded; Solidity needs overflow-safe mulDiv.
    """
    _uint(p0, "p0")
    _uint(nodes, "nodes", 1)
    _uint(buyers30d, "buyers30d")
    if not params.P0_MIN <= p0 <= params.P0_MAX:
        raise ValueError("p0 outside configured bounds")
    node_factor = BPS + params.NODE_STEP_BPS * (nodes - 1)
    demand_factor = BPS**2 + params.DEMAND_STEP_BPS * isqrt(buyers30d * BPS**2)
    raw = p0 * node_factor * demand_factor // BPS**3
    capped = min(raw, p0 * params.PRICE_CAP_MULT)
    return capped // params.PRICE_TICK * params.PRICE_TICK


@dataclass(frozen=True)
class SubmissionCost:
    fee: int
    stake: int

    @property
    def total(self) -> int:
        return self.fee + self.stake


def submission_cost(price: int | None = None, *, params=DEFAULTS) -> SubmissionCost:
    """Snapshot the fee plus stake; None means a new topic at P0_DEFAULT."""
    price = params.P0_DEFAULT if price is None else price
    _uint(price, "price", 1)
    stake = max(params.STAKE_MIN, params.STAKE_PRICE_BPS * price // BPS)
    result = SubmissionCost(params.SUBMIT_FEE, stake)
    _uint(result.total, "fee plus stake")
    return result


class DemandWindow:
    """Bounded reference ring for one topic's successful purchases.

    Views filter expired slots without mutating. Record only after a successful
    purchase, using contributor status at that time. Time cannot move backwards
    relative to recorded purchases. Access/duplicate/revocation checks are the
    caller's responsibility. Storage never grows beyond EPOCHS slots.
    """

    def __init__(self, *, params=DEFAULTS):
        self.params = params
        self._slots = [(-1, 0)] * params.EPOCHS
        self._last_timestamp = 0

    def _epoch(self, timestamp: int) -> int:
        _uint(timestamp, "timestamp")
        if timestamp < self._last_timestamp:
            raise ValueError("timestamp precedes the last purchase")
        return timestamp // self.params.EPOCH

    def buyers(self, timestamp: int) -> int:
        epoch = self._epoch(timestamp)
        return sum(count for stored_epoch, count in self._slots
                   if 0 <= epoch - stored_epoch < self.params.EPOCHS)

    def record(self, timestamp: int, *, contributor: bool) -> None:
        if type(contributor) is not bool:
            raise ValueError("contributor must be boolean")
        epoch = self._epoch(timestamp)
        self._last_timestamp = timestamp
        for slot, (stored_epoch, _) in enumerate(self._slots):
            if epoch - stored_epoch >= self.params.EPOCHS:
                self._slots[slot] = (-1, 0)
        if not contributor:
            slot = epoch % self.params.EPOCHS
            stored_epoch, count = self._slots[slot]
            count = count + 1 if stored_epoch == epoch else 1
            _uint(count, "bucket count")
            self._slots[slot] = (epoch, count)


def quality_scores(max_similarity_bps: int, correctness_bps: int,
                   usefulness_bps: int, *, params=DEFAULTS) -> dict[str, int]:
    """Raw quality components, NOT an acceptance decision.

    Duplicates and failed mandatory checks must still reject a submission even
    when correctness/usefulness make the weighted score exceed the threshold.
    """
    for name, value in (("max_similarity_bps", max_similarity_bps),
                        ("correctness_bps", correctness_bps), ("usefulness_bps", usefulness_bps)):
        _uint(value, name)
        if value > BPS:
            raise ValueError(f"{name} must be at most 10000")
    novelty = max(0, min(BPS, (params.DUP_SIMILARITY_BPS - max_similarity_bps) * BPS
                         // (params.DUP_SIMILARITY_BPS - params.NOVELTY_FLOOR_SIM_BPS)))
    return {"novelty_bps": novelty, "correctness_bps": correctness_bps,
            "usefulness_bps": usefulness_bps,
            "total_bps": (40 * novelty + 35 * correctness_bps + 25 * usefulness_bps) // 100}


def quality_factor(score_bps: int, *, approval_bps: int | None = None,
                   root: bool = False, params=DEFAULTS) -> int:
    """QF for an already accepted node. Supply approval only with quorum.

    Quorum/acceptance/early-finalization policy remains on-chain. Floor the
    combined score to integer bps before deriving the multiplier.
    """
    _uint(score_bps, "score_bps")
    if score_bps > BPS or type(root) is not bool:
        raise ValueError("invalid score or root flag")
    if root and approval_bps is not None:
        raise ValueError("root topics have no community vote")
    combined = score_bps
    if approval_bps is not None:
        _uint(approval_bps, "approval_bps")
        if approval_bps > BPS:
            raise ValueError("approval_bps must be at most 10000")
        combined = (score_bps + approval_bps) // 2
    factor = 2 * max(combined, BPS // 2) - BPS // 2
    return min(factor, params.ROOT_QF_CAP_BPS) if root else factor


def base_weight(qf_bps: int, *, params=DEFAULTS) -> int:
    _uint(qf_bps, "qf_bps")
    if not 5_000 <= qf_bps <= 15_000:
        raise ValueError("qf_bps must be between 5000 and 15000")
    return params.BASE_WEIGHT * qf_bps // BPS


def reuse_bonus(qf_bps: int, parent_count: int, parent_base: int,
                existing_bonus: int, *, same_contributor: bool = False,
                revoked: bool = False, params=DEFAULTS) -> int:
    """Bonus for one direct parent; denominator includes ineligible parents."""
    base_weight(qf_bps, params=params)  # validate QF
    _uint(parent_count, "parent_count", 1)
    _uint(parent_base, "parent_base", 1)
    _uint(existing_bonus, "existing_bonus")
    if parent_count > params.MAX_PARENTS:
        raise ValueError("too many parents")
    if type(same_contributor) is not bool or type(revoked) is not bool:
        raise ValueError("eligibility flags must be boolean")
    if same_contributor or revoked:
        return 0
    room = max(0, params.MAX_BONUS_MULT * parent_base - existing_bonus)
    return min(room, params.REUSE_BONUS * qf_bps // BPS // parent_count)
