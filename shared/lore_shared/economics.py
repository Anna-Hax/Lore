"""Pure vote, reward and royalty arithmetic for the pricing handoff.

USDC quantities are micro-units. These functions do not check identity, access,
proofs, permissions or transaction state; the contracts must enforce those.
"""

from dataclasses import dataclass

from .pricing import BPS, DEFAULTS, _uint, quality_factor

SCALE = 10**18


@dataclass(frozen=True)
class VoteOutcome:
    accepted: bool
    quorum: bool
    qf_bps: int  # zero for rejected submissions


def vote_outcome(score_bps: int, yes: int, no: int, eligible: int,
                 *, new_topic: bool = False, params=DEFAULTS) -> VoteOutcome:
    """Resolve the attachment's strict side-quorum and supermajority rules.

    A side must EXCEED eligible * QUORUM_BPS / 10000. This differs from main's
    total-vote quorum. 6667 bps is strictly above exact 2/3 (2 of 3 is insufficient).
    Early finalization must also freeze QF, not merely the boolean outcome.
    """
    for name, value in (("score_bps", score_bps), ("yes", yes), ("no", no), ("eligible", eligible)):
        _uint(value, name)
    if score_bps > BPS or yes + no > eligible or type(new_topic) is not bool:
        raise ValueError("invalid score, tally or topic flag")
    if new_topic and (yes or no or eligible):
        raise ValueError("new topics have no community electorate")
    passed = score_bps >= params.ACCEPT_SCORE_BPS
    if new_topic:
        return VoteOutcome(passed, False, quality_factor(score_bps, root=True, params=params) if passed else 0)
    quorum = max(yes, no) * BPS > eligible * params.QUORUM_BPS
    votes = yes + no
    dissent = no if passed else yes
    overturn = quorum and dissent > 0 and dissent * BPS >= votes * params.OVERTURN_BPS
    accepted = not passed if overturn else passed
    approval = yes * BPS // votes if quorum else None
    return VoteOutcome(accepted, quorum,
                       quality_factor(score_bps, approval_bps=approval, params=params) if accepted else 0)


@dataclass(frozen=True)
class SubmissionSettlement:
    refund: int
    treasury: int
    fee_per_voter: int
    slash_per_voter: int
    winners: int

    @property
    def reward_per_voter(self) -> int:
        return self.fee_per_voter + self.slash_per_voter


def settle_submission(stake: int, fee: int, *, accepted: bool,
                      verifier_passed: bool, winners: int, params=DEFAULTS) -> SubmissionSettlement:
    """Allocate snapshotted stake+fee. Winner rewards are pulled, never pushed.

    Rejection shares slash only when it agrees with the verifier. Integer
    division residue goes to treasury. Caller derives winners from the tally.
    """
    for name, value in (("stake", stake), ("fee", fee), ("winners", winners)):
        _uint(value, name)
    _uint(stake + fee, "total escrow")
    if type(accepted) is not bool or type(verifier_passed) is not bool:
        raise ValueError("verdicts must be boolean")
    fee_per = fee * params.VOTER_FEE_SHARE_BPS // BPS // winners if winners else 0
    slash_per = (stake * params.SLASH_TO_VOTERS_BPS // BPS // winners
                 if winners and not accepted and not verifier_passed else 0)
    refund = stake if accepted else 0
    treasury = stake + fee - refund - (fee_per + slash_per) * winners
    return SubmissionSettlement(refund, treasury, fee_per, slash_per, winners)


@dataclass(frozen=True)
class SaleAllocation:
    treasury: int
    accumulator_increment: int
    reserved_scaled: int


def allocate_sale(price: int, total_weight: int, *, params=DEFAULTS) -> SaleAllocation:
    """Keep fractional residue reserved instead of double-allocating it.

    inc * weight is the exact scaled liability issued. Residue stays in the
    contract; it is not swept to treasury or recycled into another cohort.
    An empty topic sends the entire sale to treasury.
    """
    _uint(price, "price")
    _uint(total_weight, "total_weight")
    if total_weight == 0:
        return SaleAllocation(price, 0, 0)
    cut = price * params.PLATFORM_CUT_BPS // BPS
    increment, reserved = divmod((price - cut) * SCALE, total_weight)
    return SaleAllocation(cut, increment, reserved)


@dataclass(frozen=True)
class Earnings:
    """All debt and credit stay scaled until an actual USDC claim."""

    weight: int = 0
    debt_scaled: int = 0
    credit_scaled: int = 0

    def __post_init__(self):
        _uint(self.weight, "weight")
        for name, value in (("debt_scaled", self.debt_scaled), ("credit_scaled", self.credit_scaled)):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")

    def accrued(self, acc: int) -> int:
        _uint(acc, "accumulator")
        value = self.credit_scaled + self.weight * acc - self.debt_scaled
        if self.weight * acc < self.debt_scaled:
            raise ValueError("accumulator moved backwards")
        return value

    def reweight(self, acc: int, new_weight: int) -> "Earnings":
        _uint(new_weight, "new_weight")
        return Earnings(new_weight, new_weight * acc, self.accrued(acc))

    def claim(self, acc: int) -> tuple[int, "Earnings"]:
        amount, remainder = divmod(self.accrued(acc), SCALE)
        return amount, Earnings(self.weight, self.weight * acc, remainder)


def redistribute_forfeiture(forfeited_scaled: int, remaining_weight: int) -> SaleAllocation:
    """Redistribute once all revoked nodes are removed, with no platform cut.

    No remaining weight: treasury receives whole micro-units; fraction remains
    reserved. Otherwise all divisible scaled liability goes to remaining nodes.
    """
    if type(forfeited_scaled) is not int or forfeited_scaled < 0:
        raise ValueError("forfeiture must be a nonnegative scaled integer")
    _uint(remaining_weight, "remaining_weight")
    if remaining_weight == 0:
        treasury, residue = divmod(forfeited_scaled, SCALE)
        return SaleAllocation(treasury, 0, residue)
    increment, residue = divmod(forfeited_scaled, remaining_weight)
    return SaleAllocation(0, increment, residue)
