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
if "validate_plaintext" not in (AGENTS / "gateway" / "service.py").read_text():
    pytest.skip("P1 has not wired validate_plaintext yet; see e2e/DELIVERY_HANDOFF.md", allow_module_level=True)
sys.path.insert(0, str(AGENTS))

from eth_account import Account  # noqa: E402
from eth_utils import keccak  # noqa: E402

from gateway import worker  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.db import connect  # noqa: E402
from gateway.indexer import apply  # noqa: E402
from gateway.service import LoreError  # noqa: E402
from lore_shared import crypto, leak, watermark  # noqa: E402
from tests.fakes import FakeChain, FakeStorage  # noqa: E402

AUTHOR, VOTER, BUYER, OTHER, REPORTER = (Account.create() for _ in range(5))
RESEARCH = "First finding on fees. Second finding on blobs. Third finding on sequencers. Fourth finding."
FOLLOW_UP = "Follow-up result one. Follow-up result two. Follow-up result three. Follow-up result four."


def b32(value: str) -> bytes:
    return bytes.fromhex(value.removeprefix("0x"))


def person(account) -> str:
    """Each test human's World ID person; the gateway is hosted and users act as their person (P1, 2026-11)."""
    return "0x" + keccak(text="person:" + account.address.lower()).hex()


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
    service = create_app(path, chain, content, storage, now=lambda: 1_000).state.service
    db, clock = connect(path), {"block": 0}

    def event(name, **args):
        clock["block"] += 1
        with db:
            apply(db, name, args, clock["block"], 0, 1_000)

    for account in (AUTHOR, VOTER, BUYER, OTHER, REPORTER):  # one wallet per World ID person
        event("AgentRegistered", agent=account.address, person=b32(person(account)))

    # An accepted node from AUTHOR, then a reported submission VOTER may read.
    first = service.prepare_submit(person(AUTHOR), RESEARCH, 0)
    event("Submitted", subId=1, topicId=0, submitter=AUTHOR.address, contentHash=b32(first["content_hash"]), storageRoot=b32(first["storage_root"]))
    event("Reported", subId=1, **{"pass": True}, parents=[], reportHash=b32("00" * 32), eligibleVoters=0)
    event("NodeAdded", topicId=1, nodeId=1, contributor=AUTHOR.address, parents=[])
    event("Finalized", subId=1, accepted=True, nodeId=1)
    second = service.prepare_submit(person(OTHER), FOLLOW_UP, 1)
    report = storage.upload(json.dumps({"parents": [], "receipts": [], "passed": True}).encode())
    event("Submitted", subId=2, topicId=1, submitter=OTHER.address, contentHash=b32(second["content_hash"]), storageRoot=b32(second["storage_root"]))
    event("Reported", subId=2, **{"pass": True}, parents=[], reportHash=b32(report), eligibleVoters=1)
    chain.votable = {(2, VOTER.address.lower())}
    chain.access.add((1, BUYER.address.lower()))
    return SimpleNamespace(chain=chain, storage=storage, service=service, db=db, event=event)


def excerpt(text: str, start: str, stop: str) -> str:
    return text[text.index(start):text.index(stop)]


def report_leak(world, report_id: int, text: str) -> None:
    posted = world.service.prepare_report_leak(person(REPORTER), 1, text)
    world.event("LeakReported", reportId=report_id, topicId=1, reporter=REPORTER.address, evidenceHash=b32(posted["evidence_hash"]))
    worker.match_leaks(world.db, world.chain, leak.best_match, set())


def test_stored_blob_is_real_ciphertext(world):
    assert world.storage.blobs
    for blob in world.storage.blobs.values():
        assert RESEARCH.encode() not in blob and FOLLOW_UP.encode() not in blob


def test_buyer_excerpt_is_traced_on_chain_with_voter_copies_present(world):
    world.service.vote_task(person(VOTER), 2)
    copy = world.service.read_topic(person(BUYER), 1)["nodes"][0]["text"]
    assert copy != RESEARCH
    report_leak(world, 1, excerpt(copy, "Second", "Fourth"))
    assert world.chain.sent == [("Reports", "recordMatch", 1, BUYER.address, 10_000)]


def test_voter_excerpt_is_traced_even_though_the_voter_never_bought(world):
    world.service.read_topic(person(BUYER), 1)
    copy = world.service.vote_task(person(VOTER), 2)["text"]
    report_leak(world, 2, excerpt(copy, "Follow-up result two", "Follow-up result four"))
    assert world.chain.sent == [("Reports", "recordMatch", 2, VOTER.address, 10_000)]


def test_fabricated_mark_accuses_nobody(world):
    world.service.read_topic(person(BUYER), 1)
    fake = watermark.FRAME + watermark.ZERO * 64 + watermark.FRAME
    report_leak(world, 3, "Second finding on blobs." + fake)
    assert world.chain.sent == []


def test_marked_copy_cannot_be_resubmitted(world):
    copy = world.service.read_topic(person(BUYER), 1)["nodes"][0]["text"]
    blobs = len(world.storage.blobs)
    with pytest.raises(LoreError, match="reserved"):
        world.service.prepare_submit(person(BUYER), copy, 1)
    assert len(world.storage.blobs) == blobs
