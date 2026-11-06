"""Everything a Lore user can do, as a World ID person. The hosted MCP tools call these.

A user is a person (their World ID nullifier). On-chain they act through wallets linked to that person in
PersonRegistry. Lore creates each person a Turnkey wallet with delegated access (gateway/turnkey.py): Lore can
sign only Lore's own calls from it (but any of them, so users keep only what they mean to spend on Lore). prepare_* builds the calls; send() signs and broadcasts them.

Plaintext only leaves after a live on-chain check: access (buyers) or vote eligibility (voters).
"""

import json
import re
import threading
import time
from contextlib import closing, contextmanager

from eth_utils import keccak
from lore_shared.constants import MAX_CHARS
from mcp.server.mcpserver.exceptions import ToolError

from gateway import proof, tasks
from gateway.db import connect, synced_block
from gateway.turnkey import RETRY_WINDOW_MS, lore_policies

INGEST_TTL = 600  # an ingest must be submitted on-chain within 10 min, so it can't skip votes assigned later
MAX_LAG = 60      # blocks (~30 s on 0G): refuse ingests while the indexer is behind, or the vote gate is blind
NO_WALLET = "You don't have a wallet yet: create one with lore_create_wallet, then fund it with 0G (gas) and USDC."
POLICY_CALLS = {"USDC": ["approve"], "Submissions": ["submit", "vote"], "Access": ["buy"], "Royalties": ["claim"],
                "Reports": ["report"]}  # everything Lore may sign from a user's wallet


class LoreError(ToolError):
    """A user-facing refusal: the MCP client shows the message as is (other exceptions are hidden as crashes)."""


def meta(raw):
    return json.loads(raw) if raw else None


class Service:
    def __init__(self, db_path: str, chain, content, storage, now=lambda: int(time.time()), provider_signer=None,
                 turnkey=None, signer=None):
        """content/storage: P3's lore_shared (crypto + watermark, storage). provider_signer(provider) -> address.
        turnkey: gateway.turnkey.Turnkey (creates wallets); signer: gateway.signer.Signer (sends from them)."""
        self.db_path, self.chain, self.content, self.storage, self.now = db_path, chain, content, storage, now
        self.provider_signer, self.turnkey, self.signer = provider_signer, turnkey, signer
        self._locks, self._guard = {}, threading.Lock()

    def _person_lock(self, person: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(person, threading.Lock())

    @contextmanager
    def tx(self):
        """One connection, committed before the caller returns anything to the user."""
        with closing(connect(self.db_path)) as conn, conn:
            yield conn

    # --- identity ---
    def wallets(self, conn, person: str) -> list[str]:
        return [r[0] for r in conn.execute("SELECT agent FROM persons WHERE person=? ORDER BY agent", (person,))]

    def _wallet(self, conn, person: str, wallet: str | None) -> str:
        """The wallet to act with: the given one if it's the person's, else their only one."""
        mine = self.wallets(conn, person)
        if not mine:
            raise LoreError(NO_WALLET)
        if wallet:
            if wallet.lower() not in mine:
                raise LoreError("that wallet isn't linked to your World ID")
            return wallet.lower()
        if len(mine) > 1:
            raise LoreError(f"you have several wallets; say which one: {', '.join(mine)}")
        return mine[0]

    def whoami(self, person: str) -> dict:
        with self.tx() as conn:
            return {"person": person, "wallets": self.wallets(conn, person)}

    # --- wallets (Turnkey, delegated access) ---
    def managed_sub_org(self, address: str) -> str | None:
        """The Turnkey sub-org of a wallet Lore manages, or None."""
        with self.tx() as conn:
            row = conn.execute("SELECT sub_org FROM turnkey_wallets WHERE address=? AND ready",
                               (address.lower(),)).fetchone()
        return row[0] if row else None

    def create_wallet(self, person: str, email: str) -> dict:
        """Create this person's Turnkey wallet (they are its only root, reachable by `email`; Lore may sign only
        Lore's calls) and link it to their person on-chain. Safe to call again: it finishes what's missing.

        The attempt (email, start time) is saved before Turnkey is called, and a retry replays the same requests
        (gateway/turnkey.py: same body, same activity), so a crash midway never leaves a second wallet."""
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""):
            raise LoreError("give the email you'll use to manage (and if needed, revoke) the wallet")
        if self.turnkey is None:
            raise LoreError("wallets aren't configured on this gateway")
        with self._person_lock(person):  # one creation per person at a time; other people aren't held up
            with self.tx() as conn:
                row = conn.execute("SELECT email, created_ms, address, ready FROM turnkey_wallets WHERE person=?",
                                   (person,)).fetchone()
                if row is None:
                    row = (email, self.now() * 1000, None, 0)
                    conn.execute("INSERT INTO turnkey_wallets (person, email, created_ms) VALUES (?, ?, ?)",
                                 (person, *row[:2]))
            email, ms, address, ready = row  # a retry reuses the first attempt's email, so it replays exactly
            if not ready:
                # ponytail: past Turnkey's 1 h replay window an unfinished setup needs a person (its requests
                # can't be replayed). Resume from get_activity / list policies if that ever happens in practice.
                if self.now() * 1000 - ms > RETRY_WINDOW_MS:
                    raise LoreError("your wallet setup started over an hour ago and didn't finish; ask Lore's team"
                                    " to complete it")
                contracts = {n: self.chain.address(n) for n in POLICY_CALLS}
                selectors = {f"{c}.{fn}": self.chain.selector(c, fn) for c, fns in POLICY_CALLS.items() for fn in fns}
                try:
                    sub, address = self.turnkey.create_wallet(
                        person, email, lambda uid: lore_policies(uid, self.chain.chain_id, contracts, selectors), ms)
                except Exception as e:
                    raise LoreError(f"creating your wallet didn't finish ({e}); call lore_create_wallet again") from e
                address = address.lower()
                with self.tx() as conn:
                    conn.execute("UPDATE turnkey_wallets SET address=?, sub_org=?, ready=1 WHERE person=?",
                                 (address, sub, person))
            if not self.chain.person_of(address):  # link it on-chain (the gateway holds REGISTRAR)
                try:
                    self.chain.send("PersonRegistry", "register", self.chain.w3.to_checksum_address(address),
                                    bytes.fromhex(person[2:]))
                except Exception as e:
                    if (self.chain.person_of(address) or "").lower() != person.lower():  # not a lost race: real failure
                        raise LoreError(f"linking your wallet to your World ID failed ({e}); call lore_create_wallet"
                                        " again") from e
        return {"address": address, "next": "fund it with 0G (gas) and USDC, then you can buy, submit and vote. Lore"
                " can spend this wallet on Lore actions, so keep only what you mean to spend here"}

    def wallet_info(self, person: str) -> dict:
        with self.tx() as conn:
            mine = self.wallets(conn, person)
            managed = {r[0] for r in conn.execute("SELECT address FROM turnkey_wallets WHERE person=? AND ready",
                                                  (person,))}
        return {"wallets": [{"address": w, "lore_can_sign": w in managed, **self.chain.balances(w)} for w in mine]}

    def send(self, prepared: dict) -> dict:
        """Sign and broadcast a prepare_* result's transactions, in order. Returns it with their hashes."""
        if self.signer is None:
            raise LoreError("transaction signing isn't configured on this gateway")
        out = dict(prepared)
        out["tx_hashes"] = self.signer.send_all(out.pop("transactions"))
        return out

    def gated(self, conn, s) -> bool:
        """True iff this on-chain submission is the content its own submitter ingested through us, recently.

        Anyone can copy a (content_hash, storage_root) pair from a failed or front-run tx and submit it; without
        this check the gateway would decrypt someone else's text for the copier's accomplices.
        """
        ing = conn.execute("SELECT * FROM ingests WHERE content_hash=?", (s["content_hash"],)).fetchone()
        return (bool(ing) and ing["storage_root"] == s["storage_root"] and ing["caller"] == s["submitter"]
                and s["submitted_at"] is not None and s["submitted_at"] - ing["ingested_at"] <= INGEST_TTL)

    def plaintext(self, content_hash: str, root: str) -> str:
        return self.content.decrypt_node(self.storage.download(root), content_hash)

    # --- public catalogue ---
    def topics(self) -> list[dict]:
        price = self.chain.topic_price()  # settable on-chain by ADMIN
        with self.tx() as conn:
            rows = conn.execute("SELECT t.id, t.meta_json, COUNT(n.id) AS n FROM topics t"
                                " LEFT JOIN nodes n ON n.topic_id=t.id GROUP BY t.id ORDER BY t.id").fetchall()
        return [{"topic_id": r["id"], "meta": meta(r["meta_json"]), "node_count": r["n"], "price": price} for r in rows]

    def topic(self, tid: int) -> dict:
        with self.tx() as conn:
            t = conn.execute("SELECT * FROM topics WHERE id=?", (tid,)).fetchone()
            if not t:
                raise LoreError("no such topic")
            nodes = conn.execute("SELECT id, contributor, meta_json FROM nodes WHERE topic_id=? ORDER BY id", (tid,)).fetchall()
            return {"topic_id": tid, "meta": meta(t["meta_json"]), "price": self.chain.topic_price(), "nodes": [{
                "node_id": n["id"], "contributor": n["contributor"], "meta": meta(n["meta_json"]),
                "parents": [e[0] for e in conn.execute("SELECT parent FROM edges WHERE child=?", (n["id"],))],
            } for n in nodes]}

    def receipt(self, root: str) -> dict:
        return json.loads(self.storage.download(root))

    # --- voting ---
    def vote_tasks(self, person: str) -> list[dict]:
        """Open vote tasks for this person (one vote per person, whichever of their wallets casts it)."""
        with self.tx() as conn:
            return self._vote_tasks(conn, person)

    def _vote_tasks(self, conn, person: str) -> list[dict]:
        seen = {}
        for w in self.wallets(conn, person):
            for t in tasks.open_vote_tasks(conn, self.chain, w, self.now()):
                seen.setdefault(t["sub_id"], t)
        return [seen[k] for k in sorted(seen)]

    def _voting_wallet(self, conn, person: str, sid: int) -> str:
        for w in self.wallets(conn, person):
            if tasks.can_vote(conn, self.chain, sid, w):
                return w
        raise LoreError("you're not eligible to vote on this submission")

    def vote_task(self, person: str, sid: int) -> dict:
        with self.tx() as conn:
            w = self._voting_wallet(conn, person, sid)
            s = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
            report = json.loads(self.storage.download(s["report_hash"]))
            # Each voter gets their own watermarked copy, so a leaked vote task is traceable. Content its submitter
            # didn't ingest is never decrypted: it may be someone else's text (see gated()).
            text = (self.content.watermark(self.plaintext(s["content_hash"], s["storage_root"]), w, f"sub:{sid}")
                    if self.gated(conn, s) else None)
            ids = [p["node_id"] for p in report["parents"]]
            parents = conn.execute(f"SELECT id, meta_json FROM nodes WHERE id IN ({','.join('?' * len(ids))})",
                                   ids).fetchall() if ids else []
            if text is not None:  # logged before the copy leaves: this transaction commits before we return
                conn.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?)", (s["topic_id"], w, f"sub:{sid}"))
        return {"sub_id": sid, "topic_id": s["topic_id"], "text": text, "report": report,
                "receipts": report.get("receipts", []),
                "parents_meta": [{"node_id": p["id"], "meta": meta(p["meta_json"])} for p in parents]}

    def prepare_vote(self, person: str, sid: int, approve: bool) -> dict:
        with self.tx() as conn:
            w = self._voting_wallet(conn, person, sid)
        return {"transactions": [self.chain.prepare("Submissions", "vote", w, sid, approve)]}

    # --- submitting ---
    def prepare_submit(self, person: str, text: str, topic_id: int = 0, wallet: str | None = None) -> dict:
        """Gate, encrypt and store the research, then return the stake approval and submit transactions."""
        if len(text) > MAX_CHARS:  # every ingest is a paid upload; cap it
            raise LoreError(f"research is longer than {MAX_CHARS} characters")
        try:  # refuse reserved watermark characters (e.g. someone's marked copy) before anything is stored
            self.content.validate_plaintext(text)
        except ValueError as e:
            raise LoreError(str(e)) from e
        with self.tx() as conn:
            w = self._wallet(conn, person, wallet)
            if self.chain.latest() - synced_block(conn) > MAX_LAG:
                raise LoreError("Lore is catching up with the chain; try again in a few seconds")
            if self._vote_tasks(conn, person):  # vote-before-submit, per person
                raise LoreError("finish your open vote tasks first (lore_my_vote_tasks)")
            ch = self.content.content_hash(text)
            prior = conn.execute("SELECT * FROM ingests WHERE content_hash=?", (ch,)).fetchone()
            if prior:
                submitted = conn.execute("SELECT 1 FROM submissions WHERE content_hash=?", (ch,)).fetchone()
                if prior["caller"] != w or submitted:
                    raise LoreError("this exact text was already submitted")
                conn.execute("UPDATE ingests SET ingested_at=?, topic_id=? WHERE content_hash=?", (self.now(), topic_id, ch))
                root = prior["storage_root"]  # a retry after the transactions failed: restart the clock
            else:
                root = self.storage.upload(self.content.encrypt_node(text, ch))
                conn.execute("INSERT INTO ingests VALUES (?, ?, ?, ?, ?)", (ch, w, root, topic_id, self.now()))
        stake = self.chain.stake()
        return {"content_hash": ch, "storage_root": root, "stake": stake, "submit_within_seconds": INGEST_TTL,
                "transactions": [
                    self.chain.prepare("USDC", "approve", w, self.chain.address("Submissions"), stake),
                    self.chain.prepare("Submissions", "submit", w, topic_id, bytes.fromhex(ch[2:]), bytes.fromhex(root[2:])),
                ]}

    # --- buying and reading ---
    def prepare_buy(self, person: str, tid: int, wallet: str | None = None) -> dict:
        with self.tx() as conn:
            w = self._wallet(conn, person, wallet)
        price = self.chain.topic_price()
        return {"price": price, "transactions": [
            self.chain.prepare("USDC", "approve", w, self.chain.address("Access"), price),
            self.chain.prepare("Access", "buy", w, tid),
        ]}

    def read_topic(self, person: str, tid: int) -> dict:
        with self.tx() as conn:
            holder = next((w for w in self.wallets(conn, person) if self.chain.has_access(tid, w)), None)  # live
            if holder is None:
                raise LoreError("buy this topic first (lore_buy)")
            nodes = conn.execute("SELECT * FROM nodes WHERE topic_id=? AND storage_root IS NOT NULL ORDER BY id",
                                 (tid,)).fetchall()
            out = [{
                "node_id": n["id"], "meta": meta(n["meta_json"]),
                "parents": [e[0] for e in conn.execute("SELECT parent FROM edges WHERE child=?", (n["id"],))],
                "text": self.content.watermark(self.plaintext(n["content_hash"], n["storage_root"]), holder,
                                               f"node:{n['id']}"),
            } for n in nodes]
            # One row per (wallet, node copy), so a leak traces to the exact copy; committed before we return.
            conn.executemany("INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?)",
                             [(tid, holder, f"node:{n['id']}") for n in nodes])
        return {"wallet": holder, "nodes": out}

    # --- royalties ---
    def _my_nodes(self, conn, person: str) -> dict[int, str]:
        mine = self.wallets(conn, person)
        rows = conn.execute(f"SELECT id, contributor FROM nodes WHERE contributor IN ({','.join('?' * len(mine))})",
                            mine).fetchall() if mine else []
        return {r[0]: r[1] for r in rows}

    def claimable(self, person: str) -> dict:
        with self.tx() as conn:
            nodes = self._my_nodes(conn, person)
        owed = {n: self.chain.claimable(n) for n in nodes}
        return {"total": sum(owed.values()), "by_node": {n: v for n, v in owed.items() if v}}

    def prepare_claim(self, person: str) -> dict:
        """One claim transaction per wallet: royalties are paid to the wallet that contributed each node."""
        with self.tx() as conn:
            nodes = self._my_nodes(conn, person)
        by_wallet = {}
        for n, w in nodes.items():
            if self.chain.claimable(n):
                by_wallet.setdefault(w, []).append(n)
        return {"transactions": [self.chain.prepare("Royalties", "claim", w, ids) for w, ids in by_wallet.items()]}

    # --- leaks ---
    def prepare_report_leak(self, person: str, tid: int, text: str, wallet: str | None = None) -> dict:
        if len(text) > MAX_CHARS:
            raise LoreError(f"evidence is longer than {MAX_CHARS} characters")
        h = "0x" + keccak(text=text).hex()
        with self.tx() as conn:
            w = self._wallet(conn, person, wallet)
            conn.execute("INSERT OR IGNORE INTO evidence VALUES (?, ?, ?)", (h, tid, text))
        return {"evidence_hash": h, "transactions": [self.chain.prepare("Reports", "report", w, tid, bytes.fromhex(h[2:]))]}

    # --- proofs ---
    def check_proof(self, root: str, claim: dict | None = None) -> dict:
        receipt = self.receipt(root)
        try:
            onchain = self.provider_signer(receipt["provider"]) if self.provider_signer else None
        except Exception:  # RPC down or provider unknown: "incomplete", never a false "pass"
            onchain = None
        return proof.check(receipt, onchain, claim)

    # --- inbox ---
    def inbox(self, person: str, take: bool = True) -> dict:
        """Open vote tasks, plus what changed since this person last looked (cleared once taken)."""
        with self.tx() as conn:
            mine = self.wallets(conn, person)
            q = ",".join("?" * len(mine))
            state = conn.execute("SELECT since_node, subs FROM inbox_state WHERE person=?", (person,)).fetchone()
            first = state is None
            since, known = (state[0], json.loads(state[1])) if state else (0, {})
            subs = conn.execute(f"SELECT id, status, node_id FROM submissions WHERE submitter IN ({q}) ORDER BY id",
                                mine).fetchall() if mine else []
            nodes = conn.execute(
                f"SELECT n.id, n.topic_id, n.meta_json FROM nodes n WHERE n.id > ? AND n.topic_id IN ("
                f" SELECT topic_id FROM purchases WHERE buyer IN ({q}) UNION SELECT topic_id FROM nodes WHERE contributor IN ({q}))"
                " ORDER BY n.id", (since, *mine, *mine)).fetchall() if mine else []
            updates = [] if first else [
                f"Your submission #{s['id']} is now {s['status']}" + (f" as node #{s['node_id']}." if s["node_id"] else ".")
                for s in subs if known.get(str(s["id"])) != s["status"]
                and not (known.get(str(s["id"])) is None and s["status"] == "Pending")
            ] + [f"New node #{n['id']} in topic {n['topic_id']}: {(meta(n['meta_json']) or {}).get('title') or '(title pending)'}"
                 for n in nodes]
            if take or first:
                latest = conn.execute("SELECT COALESCE(MAX(id), 0) FROM nodes").fetchone()[0]
                conn.execute("INSERT OR REPLACE INTO inbox_state VALUES (?, ?, ?)",
                             (person, latest, json.dumps({str(s["id"]): s["status"] for s in subs})))
            return {"vote_tasks": self._vote_tasks(conn, person), "updates": updates}

    def notice(self, person: str) -> str | None:
        box = self.inbox(person, take=False)
        v, u = len(box["vote_tasks"]), len(box["updates"])
        if not v and not u:
            return None
        parts = ([f"{v} open vote task{'s' * (v != 1)} (vote before you can submit)"] if v else []) + \
                ([f"{u} new update{'s' * (u != 1)}"] if u else [])
        return "Lore inbox: " + " and ".join(parts) + ". Call lore_inbox to see them."

    # --- Lore's own agents (internal API) ---
    def internal_plaintext(self, kind: str, iid: int) -> dict:
        with self.tx() as conn:
            if kind == "node":
                n = conn.execute("SELECT * FROM nodes WHERE id=? AND storage_root IS NOT NULL", (iid,)).fetchone()
                if not n:
                    raise LookupError("no such node")
                return {"topic_id": n["topic_id"], "ingested": True, "meta_hash": n["meta_hash"],
                        "synced_block": synced_block(conn), "text": self.plaintext(n["content_hash"], n["storage_root"])}
            s = conn.execute("SELECT * FROM submissions WHERE id=?", (iid,)).fetchone()
            if not s:
                raise LookupError("no such submission (not indexed yet?)")
            base = {"topic_id": s["topic_id"], "status": s["status"], "synced_block": synced_block(conn)}
            if not self.gated(conn, s):  # skipped the gate, someone else's content, or a stale ingest
                return {**base, "ingested": False, "text": None}
            return {**base, "ingested": True, "text": self.plaintext(s["content_hash"], s["storage_root"])}

    def internal_candidates(self, tid: int) -> dict:
        with self.tx() as conn:
            nodes = conn.execute("SELECT * FROM nodes WHERE topic_id=? AND storage_root IS NOT NULL", (tid,)).fetchall()
            pending = [s for s in conn.execute(
                "SELECT * FROM submissions WHERE topic_id=? AND status IN ('Pending', 'Reported')", (tid,)
            ).fetchall() if self.gated(conn, s)]
            t = conn.execute("SELECT meta_json FROM topics WHERE id=?", (tid,)).fetchone()
            return {
                "synced_block": synced_block(conn), "topic": meta(t["meta_json"]) if t else None,
                "nodes": [{"node_id": n["id"], "meta": meta(n["meta_json"]),
                           "text": self.plaintext(n["content_hash"], n["storage_root"])} for n in nodes],
                "pending": [{"sub_id": s["id"], "text": self.plaintext(s["content_hash"], s["storage_root"])}
                            for s in pending],
            }
