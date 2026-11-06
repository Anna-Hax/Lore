from dataclasses import replace
import random

import pytest

from lore_shared.constants import PricingParameters
from lore_shared.economics import (
    SCALE, Earnings, allocate_sale, redistribute_forfeiture, settle_submission, vote_outcome,
)

P = PricingParameters()


@pytest.mark.parametrize("score,yes,no,eligible,accepted,quorum", [
    (8000, 0, 0, 3, True, False),
    (4000, 0, 0, 3, False, False),
    (8000, 1, 2, 3, True, True),  # 2/3 < 6667 bps
    (8000, 1, 3, 4, False, True),
    (4000, 3, 1, 4, True, True),
    (4000, 3, 2, 5, False, True),
    (8000, 2, 2, 4, True, False),  # a side must strictly exceed half
    (4000, 2, 2, 4, False, False),
    (8000, 0, 2, 10, True, False),
])
def test_vote_rules(score, yes, no, eligible, accepted, quorum):
    outcome = vote_outcome(score, yes, no, eligible)
    assert (outcome.accepted, outcome.quorum) == (accepted, quorum)
    assert 5000 <= outcome.qf_bps <= 15000 if accepted else outcome.qf_bps == 0


def test_roots_and_invalid_tallies():
    assert vote_outcome(10000, 0, 0, 0, new_topic=True).qf_bps == 12000
    assert not vote_outcome(4999, 0, 0, 0, new_topic=True).accepted
    for args in [(8000, 2, 2, 3), (10001, 0, 0, 0), (True, 0, 0, 0)]:
        with pytest.raises(ValueError):
            vote_outcome(*args)
    with pytest.raises(ValueError):
        vote_outcome(8000, 1, 0, 1, new_topic=True)


def test_locked_verdict_does_not_mean_locked_quality():
    early = vote_outcome(8000, 3, 0, 5)
    later = vote_outcome(8000, 3, 2, 5)
    assert early.accepted and later.accepted
    assert early.qf_bps == 13000
    assert later.qf_bps == 9000


def test_default_submission_allocations():
    accepted = settle_submission(2_000_000, 1_000_000, accepted=True, verifier_passed=True, winners=3)
    assert (accepted.refund, accepted.treasury, accepted.reward_per_voter) == (2_000_000, 1_000_000, 0)
    rejected = settle_submission(2_000_000, 1_000_000, accepted=False, verifier_passed=False, winners=3)
    assert (rejected.refund, rejected.treasury, rejected.slash_per_voter) == (0, 2_000_001, 333333)
    overturned = settle_submission(2_000_000, 1_000_000, accepted=False, verifier_passed=True, winners=3)
    assert (overturned.treasury, overturned.reward_per_voter) == (3_000_000, 0)
    no_voters = settle_submission(2_000_000, 1_000_000, accepted=False, verifier_passed=False, winners=0)
    assert no_voters.treasury == 3_000_000


def test_optional_fee_rewards_and_random_settlement_conservation():
    rng = random.Random(104)
    for _ in range(1000):
        params = replace(P, VOTER_FEE_SHARE_BPS=rng.randrange(10001), SLASH_TO_VOTERS_BPS=rng.randrange(10001))
        stake, fee, winners = rng.randrange(100_000_000), rng.randrange(10_000_000), rng.randrange(100)
        settled = settle_submission(stake, fee, accepted=rng.choice([True, False]),
                                    verifier_passed=rng.choice([True, False]), winners=winners, params=params)
        assert settled.refund + settled.treasury + winners * settled.reward_per_voter == stake + fee
        assert min(settled.refund, settled.treasury, settled.reward_per_voter) >= 0


def test_scaled_debt_does_not_give_new_weight_old_fractional_earnings():
    # Joining at an accumulator with a non-integral micro-unit entitlement
    # must not donate the old fractional part to the joining node.
    joined = Earnings().reweight(SCALE // 2, 1)
    assert joined.accrued(SCALE // 2) == 0
    assert joined.claim(SCALE)[0] == 0
    assert joined.claim(3 * SCALE // 2)[0] == 1


def test_claim_retains_fraction_and_reweight_settles_old_weight():
    before = Earnings(3)
    amount, after = before.claim(SCALE // 2)
    assert amount == 1 and after.credit_scaled == SCALE // 2
    changed = after.reweight(SCALE // 2, 5)
    amount, after = changed.claim(SCALE)
    assert amount == 3 and after.credit_scaled == 0
    with pytest.raises(ValueError):
        after.accrued(SCALE // 2)


def test_corrected_allocation_keeps_the_two_sale_counterexample_solvent():
    allocation = allocate_sale(5_000_000, 30000)
    node = Earnings(30000)
    claim, _ = node.claim(2 * allocation.accumulator_increment)
    assert 2 * allocation.treasury + claim == 9_999_999
    assert (2 * allocation.treasury * SCALE + node.accrued(2 * allocation.accumulator_increment)
            + 2 * allocation.reserved_scaled) == 10_000_000 * SCALE


def test_zero_weight_and_forfeiture_conserve_scaled_amounts():
    empty = allocate_sale(5_000_000, 0)
    assert (empty.treasury, empty.accumulator_increment, empty.reserved_scaled) == (5_000_000, 0, 0)
    for weight in (0, 10000, 30001):
        amount = 9 * SCALE + 123
        allocation = redistribute_forfeiture(amount, weight)
        assert allocation.treasury * SCALE + allocation.accumulator_increment * weight + allocation.reserved_scaled == amount


@pytest.mark.parametrize("call", [
    lambda: Earnings(weight=True), lambda: Earnings(credit_scaled=0.5),
    lambda: allocate_sale(-1, 0), lambda: allocate_sale(1, -1),
    lambda: redistribute_forfeiture(-1, 10),
    lambda: settle_submission(1, 1, accepted=1, verifier_passed=True, winners=0),
])
def test_invalid_money_inputs(call):
    with pytest.raises(ValueError):
        call()
