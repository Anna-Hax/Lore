"""Thin web3 wrapper used by the gateway, verifier and curator, on P2's deployed contracts."""

from eth_account import Account
from web3 import Web3

import shared

# The events Lore's agents index. Contracts emit others too (role, ERC1155, params) that we ignore.
WATCHED = {
    "TopicGraph": ["TopicCreated", "NodeAdded", "NodeMetaSet", "TopicMetaSet"],
    "Submissions": ["Submitted", "Reported", "Voted", "Finalized"],
    "Access": ["Bought"],
    "Reports": ["LeakReported", "LeakMatched"],
}
STATUS = ("Pending", "Reported", "Accepted", "Rejected")  # ISubmissions.Status


def hexstr(b) -> str:
    return "0x" + bytes(b).hex()


class Chain:
    def __init__(self, rpc: str, contracts: dict[str, str], key: str | None = None):
        self.w3 = Web3(Web3.HTTPProvider(rpc))
        self.c = {n: self.w3.eth.contract(address=Web3.to_checksum_address(a), abi=shared.abi(n))
                  for n, a in contracts.items()}
        self.acct = Account.from_key(key) if key else None
        self._ts, self._roles = {}, {}

    @classmethod
    def for_chain(cls, chain_id: int, key: str | None = None, rpc: str | None = None) -> "Chain":
        return cls(rpc or shared.network(chain_id).rpc_url, shared.deployment(chain_id)["contracts"], key)

    @staticmethod
    def _a(addr: str) -> str:
        return Web3.to_checksum_address(addr)

    # --- reads (always live, never cached: BUILD_PLAN §4 C) ---
    def has_access(self, topic_id: int, addr: str) -> bool:
        return self.c["Access"].functions.hasAccess(topic_id, self._a(addr)).call()

    def contributor_since(self, topic_id: int, addr: str) -> int:
        return self.c["TopicGraph"].functions.contributorSince(topic_id, self._a(addr)).call()

    def has_role(self, role: str, addr: str) -> bool:
        """role: VERIFIER, CURATOR, LEAK_DETECTOR or ADMIN (P2's LoreRoles.<role>_ROLE)."""
        roles = self.c["LoreRoles"]
        if role not in self._roles:  # role ids are constants, safe to cache; membership is not
            self._roles[role] = getattr(roles.functions, f"{role}_ROLE")().call()
        return roles.functions.hasRole(self._roles[role], self._a(addr)).call()

    def can_vote(self, sub_id: int, addr: str) -> bool:
        return self.c["Submissions"].functions.canVote(sub_id, self._a(addr)).call()

    def can_finalize(self, sub_id: int) -> bool:
        return self.c["Submissions"].functions.canFinalize(sub_id).call()

    def voting_window(self) -> int:
        return self.c["Submissions"].functions.votingWindow().call()

    def submission_status(self, sub_id: int) -> str:
        return STATUS[self.c["Submissions"].functions.getSubmission(sub_id).call()[4]]

    def topic_price(self) -> int:
        return self.c["Access"].functions.topicPrice().call()

    def latest(self) -> int:
        return self.w3.eth.block_number

    # --- writes ---
    def send(self, contract: str, fn: str, *args):
        tx = getattr(self.c[contract].functions, fn)(*args).build_transaction(
            {"from": self.acct.address, "nonce": self.w3.eth.get_transaction_count(self.acct.address)}
        )
        h = self.w3.eth.send_raw_transaction(self.acct.sign_transaction(tx).raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(h)
        if receipt.status != 1:
            raise RuntimeError(f"{contract}.{fn} reverted: {hexstr(h)}")
        return receipt

    # --- events ---
    def logs(self, from_block: int, to_block: int, only: set[str] | None = None):
        """Yield (block, log_index, event_name, args, block_timestamp) in chain order."""
        out = []
        for name, events in WATCHED.items():
            for ev in events:
                if only and ev not in only:
                    continue
                for log in self.c[name].events[ev].get_logs(from_block=from_block, to_block=to_block):
                    out.append((log.blockNumber, log.logIndex, log.event, dict(log.args), self._time(log.blockNumber)))
        return sorted(out, key=lambda e: (e[0], e[1]))

    def _time(self, n: int) -> int:
        if n not in self._ts:
            self._ts[n] = self.w3.eth.get_block(n).timestamp
        return self._ts[n]
