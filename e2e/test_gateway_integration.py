"""P1's real gateway with P3's real crypto, watermark and leak code.

Chain and storage are P1's fakes, so this proves the library handoff, not testnet.
Skips until P1's wiring from e2e/DELIVERY_HANDOFF.md is in agents/. Then run:
    uv run --project agents --locked --with ./shared --with pytest pytest e2e/test_gateway_integration.py
"""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

AGENTS = Path(__file__).resolve().parents[1] / "agents"
if not (AGENTS / "gateway" / "app.py").is_file():
    pytest.skip("agents/ has not landed in this checkout", allow_module_level=True)
if "validate_plaintext" not in (AGENTS / "gateway" / "app.py").read_text():
    pytest.skip("P1 has not wired validate_plaintext yet; see e2e/DELIVERY_HANDOFF.md", allow_module_level=True)
sys.path.insert(0, str(AGENTS))

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gateway import worker  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.db import connect  # noqa: E402
from gateway.indexer import apply  # noqa: E402
from lore_shared import crypto, leak, watermark  # noqa: E402
from tests.fakes import FakeChain, FakeStorage  # noqa: E402

AUTHOR, VOTER, BUYER, OTHER, REPORTER = (Account.create() for _ in range(5))
RESEARCH = "First finding on fees. Second finding on blobs. Third finding on sequencers. Fourth finding."
FOLLOW_UP = "Follow-up result one. Follow-up result two. Follow-up result three. Follow-up result four."


def b32(value: str) -> bytes:
    return bytes.fromhex(value.removeprefix("0x"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_KEY", "11" * 32)
    monkeypatch.setenv("WM_SECRET", "22" * 32)
    chain, storage = FakeChain(), FakeStorage()
    content = SimpleNamespace(
        content_hash=crypto.content_hash, encrypt_node=lambda text, _hash: crypto.encrypt_node(text),
        decrypt_node=crypto.decrypt_node, watermark=watermark.watermark,
        validate_plaintext=watermark.validate_plaintext,
    )
    path = str(tmp_path / "gateway.db")
    client, db, clock = TestClient(create_app(path, chain, content, storage, now=lambda: 1_000)), connect(path), {"block": 0}

    def event(name, **args):
        clock["block"] += 1
        with db:
            apply(db, name, args, clock["block"], 0, 1_000)

    def login(account):
        message = client.post("/auth/nonce", json={"address": account.address}).json()["message"]
        signature = account.sign_message(encode_defunct(text=message)).signature.to_0x_hex()
        body = {"address": account.address, "message": message, "signature": signature}
        return {"Authorization": "Bearer " + client.post("/auth/verify", json=body).json()["token"]}

    # An accepted node from AUTHOR, then a reported submission VOTER may read.
    first = client.post("/ingest", json={"text": RESEARCH}, headers=login(AUTHOR)).json()
    event("Submitted", subId=1, topicId=0, submitter=AUTHOR.address, contentHash=b32(first["content_hash"]), storageRoot=b32(first["storage_root"]))
    event("Reported", subId=1, **{"pass": True}, parents=[], reportHash=b32("00" * 32), eligibleVoters=0)
    event("NodeAdded", topicId=1, nodeId=1, contributor=AUTHOR.address, parents=[])
    event("Finalized", subId=1, accepted=True, nodeId=1)
    second = client.post("/ingest", json={"text": FOLLOW_UP, "topic_id": 1}, headers=login(OTHER)).json()
    report = storage.upload(json.dumps({"parents": [], "receipts": [], "passed": True}).encode())
    event("Submitted", subId=2, topicId=1, submitter=OTHER.address, contentHash=b32(second["content_hash"]), storageRoot=b32(second["storage_root"]))
    event("Reported", subId=2, **{"pass": True}, parents=[], reportHash=b32(report), eligibleVoters=1)
    chain.votable = {(2, VOTER.address.lower())}
    chain.access.add((1, BUYER.address.lower()))
    return SimpleNamespace(chain=chain, storage=storage, client=client, db=db, event=event, login=login)


def excerpt(text: str, start: str, stop: str) -> str:
    return text[text.index(start):text.index(stop)]


def report_leak(world, report_id: int, text: str) -> None:
    posted = world.client.post("/leaks", json={"topic_id": 1, "text": text}, headers=world.login(REPORTER)).json()
    world.event("LeakReported", reportId=report_id, topicId=1, reporter=REPORTER.address, evidenceHash=b32(posted["evidence_hash"]))
    worker.match_leaks(world.db, world.chain, leak.best_match, set())


def test_stored_blob_is_real_ciphertext(world):
    assert world.storage.blobs
    for blob in world.storage.blobs.values():
        assert RESEARCH.encode() not in blob and FOLLOW_UP.encode() not in blob


def test_buyer_excerpt_is_traced_on_chain_with_voter_copies_present(world):
    world.client.get("/vote-tasks/2", headers=world.login(VOTER))
    copy = world.client.get("/topics/1/content", headers=world.login(BUYER)).json()["nodes"][0]["text"]
    assert copy != RESEARCH
    report_leak(world, 1, excerpt(copy, "Second", "Fourth"))
    assert world.chain.sent == [("Reports", "recordMatch", 1, BUYER.address, 10_000)]


def test_voter_excerpt_is_traced_even_though_the_voter_never_bought(world):
    world.client.get("/topics/1/content", headers=world.login(BUYER))
    copy = world.client.get("/vote-tasks/2", headers=world.login(VOTER)).json()["text"]
    report_leak(world, 2, excerpt(copy, "Follow-up result two", "Follow-up result four"))
    assert world.chain.sent == [("Reports", "recordMatch", 2, VOTER.address, 10_000)]


def test_fabricated_mark_accuses_nobody(world):
    world.client.get("/topics/1/content", headers=world.login(BUYER))
    fake = watermark.FRAME + watermark.ZERO * 64 + watermark.FRAME
    report_leak(world, 3, "Second finding on blobs." + fake)
    assert world.chain.sent == []


def test_marked_copy_cannot_be_resubmitted(world):
    copy = world.client.get("/topics/1/content", headers=world.login(BUYER)).json()["nodes"][0]["text"]
    blobs = len(world.storage.blobs)
    response = world.client.post("/ingest", json={"text": copy, "topic_id": 1}, headers=world.login(BUYER))
    assert response.status_code == 422 and len(world.storage.blobs) == blobs
