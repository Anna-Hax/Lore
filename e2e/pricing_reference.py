"""Executable economic reference for P1/P2 integration tests, not a service.

One instance is one topic. Caller identities are symbolic strings in these
offline tests. Chain roles, World ID, proofs, storage and ERC20 transfers are
outside this model. Revocation loops here describe final balances only: P2 must
implement bounded revocation before exposing the operation on-chain.
"""

from dataclasses import dataclass, field

from lore_shared.economics import Earnings, SCALE, allocate_sale, redistribute_forfeiture
from lore_shared.pricing import DEFAULTS, DemandWindow, base_weight, reuse_bonus, topic_price


@dataclass
class Node:
    contributor: str
    payee: str
    base: int
    bonus: int = 0
    earnings: Earnings = field(default_factory=Earnings)
    recovery: str | None = None
    recovery_requested_at: int | None = None


class TopicEconomy:
    def __init__(self, root_contributor: str, root_qf: int, *, params=DEFAULTS):
        if root_qf > params.ROOT_QF_CAP_BPS:
            raise ValueError("root QF exceeds cap")
        self.params = params
        self.root_contributor = root_contributor
        self.p0 = params.P0_DEFAULT
        self.initial_price_set = False
        self.sales = 0
        self.demand = DemandWindow(params=params)
        self.holders: set[str] = set()
        self.revoked: set[str] = set()
        self.nodes: dict[int, Node] = {}
        self.contributors: set[str] = set()
        self.acc = self.total_weight = 0
        self.treasury = self.reserved_scaled = 0
        self.received = self.claimed = self.treasury_withdrawn = 0
        self.add_node(1, root_contributor, root_qf, [])

    def set_initial_price(self, caller: str, p0: int) -> None:
        if caller != self.root_contributor or self.initial_price_set or self.sales:
            raise ValueError("only root contributor, once, before any sale")
        topic_price(p0, 1, 0, params=self.params)  # validates bounds and type
        self.p0, self.initial_price_set = p0, True

    def price(self, timestamp: int) -> int:
        return topic_price(self.p0, len(self.nodes), self.demand.buyers(timestamp), params=self.params)

    def buy(self, wallet: str, max_price: int, timestamp: int) -> int:
        if wallet in self.holders or wallet in self.revoked:
            raise ValueError("already held or revoked")
        price = self.price(timestamp)
        if type(max_price) is not int or max_price < price:
            raise ValueError("price exceeds maximum")
        allocation = allocate_sale(price, self.total_weight, params=self.params)
        self.demand.record(timestamp, contributor=wallet in self.contributors)
        self.holders.add(wallet)
        self.sales += 1
        self.received += price
        self.acc += allocation.accumulator_increment
        self.treasury += allocation.treasury
        self.reserved_scaled += allocation.reserved_scaled
        return price

    def can_submit(self, wallet: str) -> bool:
        return wallet in self.holders and wallet not in self.revoked

    def _weight(self, node: Node, new_weight: int) -> None:
        self.total_weight += new_weight - node.earnings.weight
        node.earnings = node.earnings.reweight(self.acc, new_weight)

    def add_node(self, node_id: int, contributor: str, qf: int, parents: list[int]) -> None:
        """An already accepted submission; submission-time access is separate."""
        if type(node_id) is not int or node_id <= 0 or node_id in self.nodes:
            raise ValueError("invalid or duplicate node")
        if contributor in self.revoked:
            raise ValueError("revoked contributor")
        if len(parents) > self.params.MAX_PARENTS or len(set(parents)) != len(parents):
            raise ValueError("too many or duplicate parents")
        if any(type(parent) is not int or parent not in self.nodes or parent >= node_id for parent in parents):
            raise ValueError("parent must be an earlier node in this topic")
        base = base_weight(qf, params=self.params)
        node = Node(contributor, contributor, base)
        self._weight(node, base)
        self.nodes[node_id] = node
        self.contributors.add(contributor)
        for parent_id in parents:
            parent = self.nodes[parent_id]
            bonus = reuse_bonus(qf, len(parents), parent.base, parent.bonus,
                                same_contributor=parent.contributor == contributor,
                                revoked=parent.earnings.weight == 0, params=self.params)
            if bonus:
                self._weight(parent, parent.earnings.weight + bonus)
                parent.bonus += bonus

    def claimable(self, node_id: int) -> int:
        return self.nodes[node_id].earnings.accrued(self.acc) // SCALE

    def claim(self, caller: str, node_ids: list[int]) -> int:
        # Validate the entire batch before changing any accounting.
        if any(self.nodes[node_id].payee != caller for node_id in node_ids):
            raise ValueError("only the node payee may claim")
        paid = 0
        for node_id in node_ids:
            node = self.nodes[node_id]
            amount, node.earnings = node.earnings.claim(self.acc)
            paid += amount
        self.claimed += paid
        return paid

    def withdraw_treasury(self) -> int:
        """Caller authorization is enforced by P2's treasury entry point."""
        amount, self.treasury = self.treasury, 0
        self.treasury_withdrawn += amount
        return amount

    def set_recovery(self, caller: str, node_ids: list[int], address: str) -> None:
        if not address or any(self.nodes[n].contributor != caller for n in node_ids):
            raise ValueError("only contributor may configure a nonempty recovery address")
        for node_id in node_ids:
            self.nodes[node_id].recovery = address
            # A changed recovery address never inherits an old pending request.
            self.nodes[node_id].recovery_requested_at = None

    def request_recovery(self, caller: str, node_ids: list[int], timestamp: int) -> None:
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("invalid timestamp")
        if any(self.nodes[n].recovery != caller or self.nodes[n].recovery_requested_at is not None
               for n in node_ids):
            raise ValueError("unauthorized or already requested recovery")
        for node_id in node_ids:
            self.nodes[node_id].recovery_requested_at = timestamp

    def cancel_recovery(self, caller: str, node_ids: list[int]) -> None:
        if any(self.nodes[n].payee != caller for n in node_ids):
            raise ValueError("only current payee may cancel")
        for node_id in node_ids:
            self.nodes[node_id].recovery_requested_at = None

    def finish_recovery(self, caller: str, node_ids: list[int], timestamp: int) -> None:
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("invalid timestamp")
        for node_id in node_ids:
            node = self.nodes[node_id]
            if (node.recovery != caller or node.recovery_requested_at is None
                    or timestamp < node.recovery_requested_at + self.params.RECOVERY_DELAY):
                raise ValueError("recovery unauthorized, cancelled or not ready")
        for node_id in node_ids:
            self.nodes[node_id].payee = caller
            self.nodes[node_id].recovery_requested_at = None

    def revoke(self, wallet: str, *, admin: bool, matched_wallet: str,
               score_bps: int, tied_wallet: bool, matched_at: int, timestamp: int) -> None:
        """A reviewed report for THIS topic, with the actual match timestamp.

        Atomic reference transition. Do not port this wallet-node loop to a
        contract: all affected weights must be excluded before redistribution,
        with claims frozen during a bounded, multi-transaction implementation.
        """
        if (admin is not True or tied_wallet is not False or wallet != matched_wallet
                or type(score_bps) is not int or not self.params.LEAK_MIN_SCORE_BPS <= score_bps <= 10000
                or type(matched_at) is not int or matched_at < 0
                or type(timestamp) is not int or timestamp < 0
                or timestamp < matched_at + self.params.REVOKE_DELAY or wallet in self.revoked):
            raise ValueError("revocation conditions not met")
        self.revoked.add(wallet)
        self.holders.discard(wallet)
        forfeiture = 0
        for node in self.nodes.values():
            if node.contributor == wallet:
                self._weight(node, 0)
                forfeiture += node.earnings.credit_scaled
                node.earnings = Earnings()
        allocation = redistribute_forfeiture(forfeiture, self.total_weight)
        self.acc += allocation.accumulator_increment
        self.treasury += allocation.treasury
        self.reserved_scaled += allocation.reserved_scaled

    def assert_conservation(self) -> None:
        accrued = sum(node.earnings.accrued(self.acc) for node in self.nodes.values())
        spent = self.claimed + self.treasury_withdrawn + self.treasury
        assert self.received * SCALE == spent * SCALE + accrued + self.reserved_scaled
