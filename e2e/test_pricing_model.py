"""Offline pricing handoff vectors, not a deployed-contract integration test."""

from lore_shared.pricing import DemandWindow, base_weight, reuse_bonus, submission_cost, topic_price
from pricing_reference import TopicEconomy
import random

import pytest


def test_alice_bob_carol_purchase_and_growth_prices():
    demand = DemandWindow()
    weights = [base_weight(10000)]
    prices = []
    for timestamp in (1, 2, 3):
        price = topic_price(5_000_000, len(weights), demand.buyers(timestamp))
        prices.append(price)
        demand.record(timestamp, contributor=False)
        if timestamp < 3:
            parents = len(weights)
            for index in range(parents):
                weights[index] += reuse_bonus(10000, parents, 10000, weights[index] - 10000)
            weights.append(base_weight(10000))
    assert prices == [5_000_000, 6_050_000, 6_840_000]
    assert weights == [14500, 11500, 10000]
    assert submission_cost(prices[-1]).total == 3_000_000


def test_proposal_dust_rule_can_double_allocate_sale_revenue():
    """Counterexample for P2: treasury dust becomes claimable in a later sale.

    One node, weight 30000, two sales of 5 USDC, platform cut 20%.
    This deliberately checks the *proposal*, not an implementation to ship.
    """
    scale, weight = 10**18, 30000
    price, cut = 5_000_000, 1_000_000
    pool = price - cut
    inc = pool * scale // weight
    dust = pool - inc * weight // scale
    acc = 2 * inc
    claimable = weight * acc // scale
    treasury = 2 * (cut + dust)
    assert dust == 1
    assert claimable == 7_999_999
    assert treasury + claimable == 2 * price + 1


def test_complete_document_example_with_corrected_royalty_accounting():
    topic = TopicEconomy("alice", 10000)
    assert topic.buy("bob", 5_000_000, 0) == 5_000_000
    topic.add_node(2, "bob", 10000, [1])
    assert topic.claimable(2) == 0
    assert topic.buy("carol", 6_050_000, 1) == 6_050_000
    topic.add_node(3, "carol", 10000, [1, 2])
    assert topic.claimable(3) == 0
    assert topic.buy("dave", 6_840_000, 2) == 6_840_000
    assert [topic.nodes[n].earnings.weight for n in (1, 2, 3)] == [14500, 11500, 10000]
    # Full micro-unit precision; the document displays only rounded cents.
    assert [topic.claimable(n) for n in (1, 2, 3)] == [8_939_652, 3_852_347, 1_520_000]
    assert topic.treasury == 3_578_000
    topic.assert_conservation()
    for node_id, wallet in enumerate(("alice", "bob", "carol"), 1):
        assert topic.claim(wallet, [node_id, node_id]) >= 0
        assert topic.claim(wallet, [node_id]) == 0
    assert topic.withdraw_treasury() == 3_578_000
    assert topic.withdraw_treasury() == 0
    topic.assert_conservation()


def test_price_lock_slippage_and_access_rules():
    topic = TopicEconomy("alice", 10000)
    assert not topic.can_submit("alice")
    with pytest.raises(ValueError):
        topic.set_initial_price("bob", 1_000_000)
    topic.set_initial_price("alice", 2_000_000)
    with pytest.raises(ValueError):
        topic.set_initial_price("alice", 3_000_000)
    with pytest.raises(ValueError):
        topic.buy("bob", 1_999_999, 0)
    assert topic.sales == 0 and topic.received == 0 and topic.demand.buyers(0) == 0
    assert topic.buy("alice", 100_000_000, 0) == 2_000_000
    assert topic.can_submit("alice") and topic.demand.buyers(0) == 0
    with pytest.raises(ValueError):
        topic.buy("alice", 100_000_000, 0)
    default = TopicEconomy("alice", 10000)
    default.buy("bob", 5_000_000, 0)
    with pytest.raises(ValueError):
        default.set_initial_price("alice", 2_000_000)


def test_recovery_delay_cancellation_and_payee_authority():
    topic = TopicEconomy("alice", 10000)
    topic.buy("bob", 5_000_000, 0)
    with pytest.raises(ValueError):
        topic.request_recovery("backup", [1], 0)
    topic.set_recovery("alice", [1], "backup")
    topic.request_recovery("backup", [1], 0)
    delay = topic.params.RECOVERY_DELAY
    with pytest.raises(ValueError):
        topic.finish_recovery("backup", [1], delay - 1)
    with pytest.raises(ValueError):
        topic.finish_recovery("backup", [1], float("nan"))
    topic.cancel_recovery("alice", [1])
    with pytest.raises(ValueError):
        topic.finish_recovery("backup", [1], delay)
    topic.request_recovery("backup", [1], 1)
    topic.finish_recovery("backup", [1], delay + 1)
    with pytest.raises(ValueError):
        topic.claim("alice", [1])
    assert topic.claim("backup", [1]) == 4_000_000
    assert not topic.can_submit("backup")  # recovery never transfers an access pass
    topic.assert_conservation()


def revoke(topic, wallet, **overrides):
    arguments = dict(admin=True, matched_wallet=wallet, score_bps=9000,
                     tied_wallet=False, matched_at=100, timestamp=100 + topic.params.REVOKE_DELAY)
    arguments.update(overrides)
    topic.revoke(wallet, **arguments)


@pytest.mark.parametrize("overrides", [
    {"admin": False}, {"score_bps": 8999}, {"tied_wallet": True},
    {"matched_wallet": "someone_else"}, {"timestamp": 100},
    {"timestamp": float("nan")},
])
def test_revocation_requires_all_review_conditions(overrides):
    topic = TopicEconomy("alice", 10000)
    with pytest.raises(ValueError):
        revoke(topic, "alice", **overrides)
    assert topic.nodes[1].earnings.weight == 10000


def test_revocation_forfeits_all_nodes_once_and_preserves_earlier_parent_bonuses():
    topic = TopicEconomy("alice", 10000)
    topic.buy("bob", 5_000_000, 0)
    topic.add_node(2, "bob", 10000, [1])
    topic.add_node(3, "bob", 10000, [1, 2])
    topic.buy("carol", 100_000_000, 1)
    alice_before = topic.claimable(1)
    weights_before = topic.nodes[1].earnings.weight
    revoke(topic, "bob")
    assert not topic.can_submit("bob")
    assert topic.claimable(2) == topic.claimable(3) == 0
    assert topic.claimable(1) > alice_before
    assert topic.total_weight == weights_before
    assert topic.nodes[1].earnings.weight == weights_before
    with pytest.raises(ValueError):
        topic.buy("bob", 100_000_000, 2)
    with pytest.raises(ValueError):
        revoke(topic, "bob")
    topic.assert_conservation()


def test_no_remaining_weights_forfeiture_and_later_sales_go_to_treasury():
    topic = TopicEconomy("alice", 10000)
    topic.buy("bob", 5_000_000, 0)
    revoke(topic, "alice")
    assert topic.total_weight == 0 and topic.treasury == 5_000_000
    before = topic.treasury
    price = topic.buy("carol", 100_000_000, 1)
    assert topic.treasury == before + price
    topic.assert_conservation()


def test_random_sales_weights_claims_and_revocations_conserve_every_scaled_unit():
    rng = random.Random(1182)
    topic = TopicEconomy("root", 12000)
    for step in range(1, 501):
        wallet = f"wallet-{step}"
        topic.buy(wallet, 1_000_000_000, step)
        if rng.randrange(3):
            node_id = len(topic.nodes) + 1
            parents = rng.sample(list(topic.nodes), min(len(topic.nodes), rng.randrange(6)))
            topic.add_node(node_id, wallet, rng.randrange(5000, 15001), parents)
            assert topic.claimable(node_id) == 0
        if rng.randrange(4) == 0:
            node_id = rng.choice(list(topic.nodes))
            topic.claim(topic.nodes[node_id].payee, [node_id])
        if rng.randrange(20) == 0:
            node = rng.choice(list(topic.nodes.values()))
            if node.contributor not in topic.revoked:
                revoke(topic, node.contributor)
        if rng.randrange(10) == 0:
            topic.withdraw_treasury()
        topic.assert_conservation()
        liabilities = sum(topic.claimable(n) for n in topic.nodes)
        assert topic.claimed + liabilities + topic.treasury + topic.treasury_withdrawn <= topic.received
