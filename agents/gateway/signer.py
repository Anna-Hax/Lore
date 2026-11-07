"""Send a person's Lore transactions from their Turnkey wallet (gateway/turnkey.py).

Lore prepares each call (chain.prepare), Turnkey signs it under that wallet's policies, and the gateway
broadcasts it and waits for the receipt. Sends from one wallet are serialized so nonces never collide.
Every failure reaches the user as a LoreError that says what happened and what was already sent.
"""

import threading

import httpx
from web3.exceptions import TimeExhausted

from gateway.service import LoreError
from gateway.turnkey import MAX_GAS, TurnkeyError, unsigned_eip1559


class Signer:
    def __init__(self, chain, turnkey, wallets):
        """wallets(address) -> Turnkey sub-org id, or None if Lore doesn't manage that wallet (or its setup
        hasn't finished, so its policies might not be in place yet)."""
        self.chain, self.turnkey, self.wallets = chain, turnkey, wallets
        self._locks, self._guard = {}, threading.Lock()

    def _lock(self, address: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(address.lower(), threading.Lock())

    def send(self, tx: dict) -> str:
        """Sign and broadcast one prepared call ({chain_id, from, to, value, data, description}). Returns its hash."""
        sender, what = tx["from"], tx["description"]
        sub_org = self.wallets(sender)
        if sub_org is None:
            raise LoreError(f"{sender} isn't a Lore-managed wallet, so Lore can't sign for it (lore_create_wallet)")
        w3 = self.chain.w3
        with self._lock(sender):
            call = {"from": sender, "to": tx["to"], "value": tx["value"], "data": tx["data"]}
            try:
                gas = w3.eth.estimate_gas(call)
            except Exception as e:  # reverts, missing allowance, no 0G for gas...
                raise LoreError(f"{what} would fail: {e}. Is your wallet {sender} funded with enough 0G?") from e
            if gas > MAX_GAS:
                raise LoreError(f"{what} needs {gas} gas, more than Lore's wallet policy allows ({MAX_GAS})")
            tip = w3.eth.max_priority_fee
            base = w3.eth.get_block("latest").get("baseFeePerGas") or w3.eth.gas_price  # pre-London blocks have none
            full = {"chainId": tx["chain_id"], "nonce": w3.eth.get_transaction_count(sender, "pending"),
                    "to": tx["to"], "value": tx["value"], "data": tx["data"], "gas": min(gas * 6 // 5, MAX_GAS),
                    "maxPriorityFeePerGas": tip, "maxFeePerGas": base * 2 + tip, "accessList": []}
            try:
                raw = self.turnkey.sign_transaction(sub_org, sender, unsigned_eip1559(full))
            except (TurnkeyError, httpx.HTTPError) as e:
                raise LoreError(f"Turnkey didn't sign {what}: {e}") from e
            try:
                h = w3.eth.send_raw_transaction(raw)
            except Exception as e:
                raise LoreError(f"the chain refused {what}: {e}") from e
            try:
                receipt = w3.eth.wait_for_transaction_receipt(h)
            except TimeExhausted as e:
                raise LoreError(f"{what} was sent (tx {h.to_0x_hex()}) but isn't mined yet; check it later") from e
        if receipt["status"] != 1:
            raise LoreError(f"{what} reverted on-chain (tx {h.to_0x_hex()})")
        return h.to_0x_hex()

    def send_all(self, txs: list[dict]) -> list[str]:
        """In order: each waits for the previous (e.g. several royalty claims). If one fails,
        the error lists the transactions that already went through, so the user knows what happened."""
        done = []
        for tx in txs:
            try:
                done.append(self.send(tx))
            except LoreError as e:
                if done:
                    raise LoreError(f"{e} (already sent: {', '.join(done)})") from e
                raise
        return done
