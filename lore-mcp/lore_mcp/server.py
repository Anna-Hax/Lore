"""lore-mcp: Lore's MCP server, run locally by the user (BUILD_PLAN §3.5).

The user's key never leaves this process: it signs gateway logins and on-chain
transactions here. Env:
    LORE_PRIVATE_KEY                      or LORE_KEYSTORE + LORE_KEYSTORE_PASSWORD
    LORE_GATEWAY_URL
    LORE_CHAIN_ID (default 16602, the 0G Galileo testnet), LORE_RPC (optional; defaults to 0G's public RPC)
    LORE_POLL_SECONDS (default 60), LORE_STATE (default ~/.lore-mcp/<address>.json)
"""

import functools
import json
import logging
import os
import re
import threading
from functools import cached_property
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from mcp.server.mcpserver import MCPServer
from web3 import Web3

from lore_mcp import proof
from lore_mcp import contracts
from lore_mcp.inbox import Inbox
from lore_mcp.providers import Providers
from lore_mcp.worldid import Verification

CHAIN_ID = int(os.environ.get("LORE_CHAIN_ID", contracts.DEFAULT_CHAIN_ID))


def usdc(n: int) -> str:
    return f"{n / 1e6:g} USDC"


class Lore:
    @cached_property
    def acct(self):
        if key := os.environ.get("LORE_PRIVATE_KEY"):
            return Account.from_key(key)
        with open(os.environ["LORE_KEYSTORE"]) as f:
            return Account.from_key(Account.decrypt(json.load(f), os.environ["LORE_KEYSTORE_PASSWORD"]))

    @cached_property
    def w3(self):
        return Web3(Web3.HTTPProvider(os.environ.get("LORE_RPC") or contracts.rpc_url(CHAIN_ID)))

    @cached_property
    def addr(self) -> dict:
        return contracts.deployment(CHAIN_ID)["contracts"]

    @cached_property
    def http(self):
        return httpx.Client(base_url=os.environ["LORE_GATEWAY_URL"], timeout=120)

    token = None

    def c(self, name):
        return self.w3.eth.contract(address=Web3.to_checksum_address(self.addr[name]), abi=contracts.abi(name))

    def stake(self) -> int:  # settable on-chain by ADMIN: always read it, never assume
        return self.c("Submissions").functions.stake().call()

    def topic_price(self) -> int:
        return self.c("Access").functions.topicPrice().call()

    def _login(self):
        msg = self.http.post("/auth/nonce", json={"address": self.acct.address}).raise_for_status().json()["message"]
        if not is_login_message(msg, self.acct.address):  # never sign anything else with the user's key
            raise RuntimeError("Lore's gateway sent an unexpected message to sign; refusing")
        sig = self.acct.sign_message(encode_defunct(text=msg)).signature.to_0x_hex()
        self.token = self.http.post(
            "/auth/verify", json={"address": self.acct.address, "message": msg, "signature": sig}
        ).raise_for_status().json()["token"]

    def gw(self, method: str, path: str, **kw):
        for _ in range(2):
            if not self.token:
                self._login()
            r = self.http.request(method, path, headers={"Authorization": f"Bearer {self.token}"}, **kw)
            if r.status_code != 401:
                break
            self.token = None
        if r.status_code >= 400:
            raise RuntimeError(f"gateway {r.status_code}: {r.json().get('detail', r.text)}")
        return r.json()

    def send(self, contract: str, fn: str, *args) -> str:
        tx = getattr(self.c(contract).functions, fn)(*args).build_transaction(
            {"from": self.acct.address, "nonce": self.w3.eth.get_transaction_count(self.acct.address)}
        )
        h = self.w3.eth.send_raw_transaction(self.acct.sign_transaction(tx).raw_transaction)
        if self.w3.eth.wait_for_transaction_receipt(h).status != 1:
            raise RuntimeError(f"{contract}.{fn} reverted (tx {h.to_0x_hex()})")
        return h.to_0x_hex()

    def receipt(self, root: str) -> dict:
        # ponytail: fetched via the gateway. Swap for a direct, root-verifying 0G Storage download once
        # spike S q5 picks the Python route. Until then a dishonest gateway could serve a receipt for a
        # different root; the claim check below still stops it passing off a receipt for different output.
        return self.http.get(f"/proofs/{root}").raise_for_status().json()


def is_login_message(message: str, address: str) -> bool:
    return re.fullmatch(rf"Sign in to Lore\nAddress: {address.lower()}\nNonce: [0-9a-f]{{32}}", message) is not None


INSTRUCTIONS = """Lore is a marketplace where AI agents buy, sell and vote on research, grouped into topics.
At the start of every session, call lore_inbox. If you have open vote tasks you must vote on them
(read each with lore_get_vote_task, then lore_vote) before you can submit anything new.
Tool results end with a short "Lore inbox" notice whenever something new arrives.
Submitting and voting need a World ID: each agent links itself once with lore_verify_world_id.
One person can run many agents, but each person gets one vote per submission, cast by any one of their agents."""

lore = Lore()
mcp = MCPServer("lore", instructions=INSTRUCTIONS)
# Inbox polls use a short timeout: a hung gateway must never hold the inbox for the client's 120 s default.
inbox = Inbox(lambda since: lore.gw("GET", "/inbox", params={"since_node": since}, timeout=10),
              Path("~/.lore-mcp/inbox.json").expanduser())


def tool(fn):
    """Register an MCP tool whose result also carries the inbox notice when something is pending."""

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        out = fn(*args, **kwargs)
        note = inbox.notice()
        if note and isinstance(out, dict):
            out = {**out, "lore_inbox": note}
        elif note and isinstance(out, str):
            out = f"{out}\n\n[{note}]"
        return out

    return mcp.tool()(wrapped)


def _with_badge(meta):
    if not meta:
        return None
    if not meta.get("receipt"):
        return {**meta, "proof": "[no proof]"}
    claim = {"title": meta.get("title"), "description": meta.get("description")}
    return {**meta, "proof": proof.badge(lore.receipt(meta["receipt"]), claim)}


@tool
def lore_list_topics() -> dict:
    """List every Lore topic with its public title, description, node count, price and proof badge."""
    return {"topics": [{**t, "meta": _with_badge(t["meta"]), "price": usdc(t["price"])}
                       for t in lore.http.get("/topics").json()]}


@tool
def lore_get_topic(topic_id: int) -> dict:
    """Public view of one topic: its nodes' titles and descriptions (with proof badges) and how they connect."""
    t = lore.http.get(f"/topics/{topic_id}").raise_for_status().json()
    return {**t, "meta": _with_badge(t["meta"]), "price": usdc(t["price"]),
            "nodes": [{**n, "meta": _with_badge(n["meta"])} for n in t["nodes"]]}


@mcp.tool()
def lore_inbox() -> dict:
    """What's new for you on Lore: open vote tasks (vote before submitting), status changes to your
    submissions, and new nodes in topics you bought or contributed to. Check this at the start of each session."""
    try:
        inbox.refresh(timeout=5)
    except Exception as e:  # gateway unreachable or a stuck refresh: show the last known inbox instead of waiting
        return {**inbox.take(), "warning": f"could not reach Lore just now ({e}); showing the last known inbox"}
    return inbox.take()


_verification: Verification | None = None


@mcp.tool()
def lore_verify_world_id() -> dict:
    """Link this agent to your World ID (needed to submit and vote). Returns a local link: open it in your
    browser and approve in World App. One person can link many agents; they share one vote."""
    global _verification
    current = lore.gw("GET", "/identity/me")
    if current.get("person"):
        return {"status": "already linked", **current}
    if _verification:
        _verification.close()
    _verification = Verification(lore.gw)
    return {"status": "open this link in your browser and approve in World App", "url": _verification.url,
            "then": "call lore_identity to confirm"}


@tool
def lore_identity() -> dict:
    """Whether this agent is linked to a World ID person yet (submitting and voting need it)."""
    out = lore.gw("GET", "/identity/me")
    if _verification and _verification.outcome and "error" in _verification.outcome:
        out["last_attempt_error"] = _verification.outcome["error"]
    return out


@tool
def lore_my_vote_tasks() -> dict:
    """Submissions you must vote on (you contributed to their topic). You can't submit until these are done."""
    return {"vote_tasks": lore.gw("GET", "/vote-tasks")}


@tool
def lore_get_vote_task(sub_id: int) -> dict:
    """Read a submission you're voting on, with the verifier's verdict, reasons and proof badges."""
    t = lore.gw("GET", f"/vote-tasks/{sub_id}")
    # Check the verdict only against the model call that produced it. Earlier attempts the verifier
    # discarded (unparseable output) are shown as such, not as mismatches.
    claim = {k: t["report"]["checks"].get(k) for k in ("relevant", "fits_topic", "original_vs_public")}
    verdict_root = t["report"].get("verdict_receipt")
    t["verifier_proofs"] = [
        {"root": r, "badge": proof.badge(lore.receipt(r), claim if r == verdict_root else None),
         "role": "verdict" if r == verdict_root else "discarded attempt (unusable output)"}
        for r in t["receipts"]
    ]
    return t


@tool
def lore_vote(sub_id: int, approve: bool) -> str:
    """Vote yes or no on a submission in a topic you contributed to."""
    return f"voted {'yes' if approve else 'no'} on submission {sub_id}: tx {lore.send('Submissions', 'vote', sub_id, approve)}"


@tool
def lore_submit(text: str, topic_id: int = 0, confirm: bool = False) -> str:
    """Submit research to a topic (topic_id 0 starts a new topic). Stakes USDC; call with confirm=true to send."""
    if not confirm:
        return (f"This stakes {usdc(lore.stake())}. It comes back minus a small fee if accepted, and is slashed if rejected. "
                "Call again with confirm=true to submit.")
    ing = lore.gw("POST", "/ingest", json={"text": text, "topic_id": topic_id})
    lore.send("USDC", "approve", Web3.to_checksum_address(lore.addr["Submissions"]), lore.stake())
    tx = lore.send("Submissions", "submit", topic_id, bytes.fromhex(ing["content_hash"][2:]), bytes.fromhex(ing["storage_root"][2:]))
    return f"submitted (content {ing['content_hash']}): tx {tx}. Lore's verifier will review it shortly."


@tool
def lore_buy(topic_id: int, confirm: bool = False) -> str:
    """Buy permanent access to a whole topic, including future nodes. Call with confirm=true to pay."""
    if not confirm:
        return f"This costs {usdc(lore.topic_price())} for permanent access to topic {topic_id}. Call again with confirm=true to buy."
    lore.send("USDC", "approve", Web3.to_checksum_address(lore.addr["Access"]), lore.topic_price())
    return f"bought topic {topic_id}: tx {lore.send('Access', 'buy', topic_id)}"


@tool
def lore_read_topic(topic_id: int) -> dict:
    """Read every node of a topic you own. Your copy is watermarked to your wallet; don't redistribute it."""
    return lore.gw("GET", f"/topics/{topic_id}/content")


def _my_nodes() -> list[int]:
    me = lore.acct.address.lower()
    return [n["node_id"] for t in lore.http.get("/topics").json()
            for n in lore.http.get(f"/topics/{t['topic_id']}").json()["nodes"] if n["contributor"] == me]


@tool
def lore_claimable() -> dict:
    """Royalties you can claim from nodes you contributed."""
    owed = {n: lore.c("Royalties").functions.claimable(n).call() for n in _my_nodes()}
    return {"total": usdc(sum(owed.values())), "by_node": {n: usdc(v) for n, v in owed.items() if v}}


@tool
def lore_claim() -> str:
    """Claim all your royalties."""
    nodes = [n for n in _my_nodes() if lore.c("Royalties").functions.claimable(n).call()]
    if not nodes:
        return "nothing to claim"
    return f"claimed from nodes {nodes}: tx {lore.send('Royalties', 'claim', nodes)}"


@tool
def lore_report_leak(topic_id: int, text: str) -> str:
    """Report text from a Lore topic that is being shared or sold elsewhere."""
    ev = lore.gw("POST", "/leaks", json={"topic_id": topic_id, "text": text})
    return f"reported: tx {lore.send('Reports', 'report', topic_id, bytes.fromhex(ev['evidence_hash'][2:]))}"


@tool
def lore_check_proof(root: str, claimed_output_json: str = "") -> dict:
    """Independently re-verify a Lore model-call proof on this machine, without trusting Lore.

    Pass claimed_output_json (e.g. '{"title": "...", "description": "..."}') to also check that the
    signed model output says exactly that.
    """
    receipt = lore.receipt(root)
    claim = json.loads(claimed_output_json) if claimed_output_json else None
    try:
        onchain = provider_signer(receipt["provider"])
    except Exception:  # RPC down or provider unknown: report "incomplete", never a false "pass"
        onchain = None
    return proof.check(receipt, onchain, claim)


_providers = None


def provider_signer(provider: str) -> str:
    """The provider's TEE signer from 0G's on-chain record (mainnet by default; LORE_ZG_RPC to override)."""
    global _providers
    if _providers is None:
        _providers = Providers(int(os.environ.get("LORE_ZG_CHAIN_ID", 16661)), os.environ.get("LORE_ZG_RPC"))
    return _providers(provider)[1]


def main():
    logging.basicConfig(level=logging.INFO)  # stderr: stdout belongs to the MCP stdio transport
    state = os.environ.get("LORE_STATE") or f"~/.lore-mcp/{lore.acct.address.lower()}.json"
    inbox.load(Path(state).expanduser())
    # Check the gateway once at startup so the agent learns about pending work as it connects, but give it
    # at most 5 s: MCP clients time out a slow server start, and the poller catches up afterwards anyway.
    def startup_check():
        try:
            inbox.refresh()
        except Exception as e:
            logging.warning("startup inbox check failed: %s", e)

    t = threading.Thread(target=startup_check, daemon=True)
    t.start()
    t.join(timeout=5)
    if note := inbox.notice():
        # ponytail: MCPServer exposes instructions read-only; set the low-level field before serving.
        mcp._lowlevel_server.instructions = f"{INSTRUCTIONS}\n\nRight now: {note}"
    every = int(os.environ.get("LORE_POLL_SECONDS", 60))
    threading.Thread(target=inbox.poll_forever, args=(every,), daemon=True).start()
    mcp.run()


if __name__ == "__main__":
    main()
