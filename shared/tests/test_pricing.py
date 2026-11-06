from dataclasses import asdict, replace
from decimal import Decimal, localcontext, ROUND_FLOOR
import random

import pytest

from lore_shared.constants import PricingParameters
from lore_shared.pricing import (
    DemandWindow, base_weight, quality_factor, quality_scores, reuse_bonus,
    submission_cost, topic_price,
)

P = PricingParameters()


@pytest.mark.parametrize("nodes,buyers,expected", [
    (1, 0, 5_000_000), (2, 1, 6_050_000), (3, 2, 6_840_000),
    (5, 16, 9_800_000), (10, 100, 19_000_000), (200, 0, 100_000_000),
    (200, 1_000_000, 100_000_000),
])
def test_document_price_vectors(nodes, buyers, expected):
    assert topic_price(P.P0_DEFAULT, nodes, buyers) == expected


def test_price_matches_decimal_oracle_with_four_sqrt_decimals():
    rng = random.Random(193)
    with localcontext() as ctx:
        ctx.prec = 70
        for _ in range(500):
            p0 = rng.randrange(P.P0_MIN, P.P0_MAX + 1)
            nodes, buyers = rng.randrange(1, 80), rng.randrange(1000)
            sqrt = Decimal(buyers).sqrt().quantize(Decimal(".0001"), rounding=ROUND_FLOOR)
            raw = p0 * (1 + Decimal(".1") * (nodes - 1)) * (1 + Decimal(".1") * sqrt)
            expected = int(min(raw, 20 * p0) // P.PRICE_TICK) * P.PRICE_TICK
            assert topic_price(p0, nodes, buyers) == expected


def test_multiply_before_dividing_preserves_fractional_bps():
    params = replace(P, PRICE_TICK=1)
    assert topic_price(5_000_000, 3, 2, params=params) == 6_848_520
    assert topic_price(5_000_000, 2**256 - 1, 2**256 - 1) == 100_000_000


@pytest.mark.parametrize("args", [(0, 1, 0), (5_000_000, 0, 0),
                                     (5_000_000, 1, -1), (5_000_000, True, 0),
                                     (5_000_000, 1, 2.0), (50_000_001, 1, 0)])
def test_price_rejects_invalid_inputs(args):
    with pytest.raises(ValueError):
        topic_price(*args)


def test_demand_expiry_is_a_view_and_contributors_do_not_increase_demand():
    window = DemandWindow()
    window.record(0, contributor=False)
    window.record(P.EPOCH - 1, contributor=False)
    window.record(P.EPOCH, contributor=False)
    window.record(P.EPOCH, contributor=True)
    assert window.buyers(P.EPOCH) == 3
    assert window.buyers(6 * P.EPOCH - 1) == 3
    assert window.buyers(6 * P.EPOCH) == 1
    assert window.buyers(7 * P.EPOCH) == 0
    # Future queries did not destroy the stored buckets.
    assert window.buyers(P.EPOCH) == 3
    window.record(1000 * P.EPOCH, contributor=False)
    assert window.buyers(1000 * P.EPOCH) == 1
    assert len(window._slots) == 6


def test_demand_random_sequence_matches_history_oracle():
    rng = random.Random(281)
    window, history, timestamp = DemandWindow(), [], 0
    for _ in range(800):
        timestamp += rng.randrange(2 * P.EPOCH)
        contributor = rng.choice([True, False])
        epoch = timestamp // P.EPOCH
        expected = sum(0 <= epoch - old < P.EPOCHS for old in history)
        assert window.buyers(timestamp) == expected
        window.record(timestamp, contributor=contributor)
        if not contributor:
            history.append(epoch)
        assert window.buyers(timestamp) == expected + int(not contributor)


def test_window_rejects_time_reversal_and_nonboolean_eligibility():
    window = DemandWindow()
    window.record(100, contributor=True)
    with pytest.raises(ValueError):
        window.record(99, contributor=False)
    with pytest.raises(ValueError):
        window.buyers(99)
    with pytest.raises(ValueError):
        window.record(100, contributor=1)


def test_stake_is_separate_from_fee_and_cost_is_a_snapshot():
    initial = submission_cost()
    assert (initial.fee, initial.stake, initial.total) == (1_000_000, 2_000_000, 3_000_000)
    assert submission_cost(100_000_000).total == 11_000_000
    assert initial.total == 3_000_000
    assert submission_cost(20_000_010).stake == 2_000_001


@pytest.mark.parametrize("overrides", [
    {"P0_MIN": 0}, {"P0_DEFAULT": 100}, {"PRICE_TICK": 0}, {"EPOCH": 0},
    {"EPOCHS": 7}, {"PLATFORM_CUT_BPS": 10001}, {"STAKE_MIN": True},
    {"ROOT_QF_CAP_BPS": 16000}, {"NOVELTY_FLOOR_SIM_BPS": 9200},
    {"BASE_WEIGHT": 0}, {"MAX_PARENTS": 6}, {"PRICE_CAP_MULT": 2**256 - 1},
])
def test_parameter_validation(overrides):
    with pytest.raises(ValueError):
        replace(P, **overrides)


def test_live_config_check_has_no_default_fallback():
    live = asdict(P)
    P.assert_matches(live)
    for bad in ({}, {**live, "PLATFORM_CUT_BPS": 1000}, {**live, "EPOCHS": "6"}):
        with pytest.raises(ValueError, match="pricing parameter mismatch"):
            P.assert_matches(bad)


def test_quality_novelty_and_weight_vectors():
    assert quality_scores(5000, 8000, 6000) == {
        "novelty_bps": 10000, "correctness_bps": 8000,
        "usefulness_bps": 6000, "total_bps": 8300,
    }
    assert quality_scores(7100, 10000, 10000)["total_bps"] == 8000
    assert quality_scores(0, 0, 0)["novelty_bps"] == 10000
    # Raw quality alone cannot enforce the duplicate rejection rule.
    assert quality_scores(9200, 10000, 10000)["total_bps"] == 6000
    assert [quality_factor(s) for s in (0, 5000, 7500, 10000)] == [5000, 5000, 10000, 15000]
    assert quality_factor(10000, root=True) == 12000
    assert quality_factor(10000, approval_bps=5000) == 10000
    assert quality_factor(8001, approval_bps=5000) == 8000
    assert base_weight(12000) == 12000


def test_parent_bonus_uses_all_parents_and_caps_each_parent():
    assert reuse_bonus(10000, 2, 10000, 0) == 1500
    assert reuse_bonus(10000, 2, 10000, 0, same_contributor=True) == 0
    assert reuse_bonus(10000, 2, 10000, 0, revoked=True) == 0
    assert reuse_bonus(10000, 2, 10000, 19500) == 500
    assert reuse_bonus(15000, 1, 10000, 20000) == 0
    assert reuse_bonus(15000, 1, 10000, 25000) == 0
    with pytest.raises(ValueError):
        reuse_bonus(10000, 6, 10000, 0)
    with pytest.raises(ValueError):
        quality_factor(10000, approval_bps=10000, root=True)


def test_custom_parameters_change_the_model():
    params = replace(P, NODE_STEP_BPS=2000, DEMAND_STEP_BPS=2000,
                     PRICE_CAP_MULT=2, EPOCH=10, EPOCHS=2, STAKE_MIN=1)
    assert topic_price(5_000_000, 2, 1, params=params) == 7_200_000
    assert topic_price(5_000_000, 100, 100, params=params) == 10_000_000
    assert submission_cost(params=params).stake == 500_000
    window = DemandWindow(params=params)
    window.record(0, contributor=False)
    assert window.buyers(19) == 1
    assert window.buyers(20) == 0
