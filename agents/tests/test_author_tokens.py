"""Author tokens (comfy): linking needs the token creator's signature; no token, no submission; vault claims."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from gateway.service import LoreError, Service
from tests.fakes import FakeChain, FakeContent, FakeStorage

PERSON = "0x" + "cd" * 32
AGENT = Account.create()
CREATOR = Account.create()  # the wallet that launched the token on comfy
TOKEN = "0x" + "77" * 20
POOL = "0x" + "88" * 32


@pytest.fixture
def svc(tmp_path):
    chain = FakeChain()
    chain.launches = {TOKEN: {"pool_id": POOL, "creator": CREATOR.address.lower()}}
    chain.tokenless, chain.locks = set(), {}
    s = Service(str(tmp_path / "g.db"), chain, FakeContent(), FakeStorage(), lambda: 1_000)
    with s.tx() as conn:
        conn.execute("INSERT INTO persons VALUES (?, ?)", (AGENT.address.lower(), PERSON))
    return s


def sign(acct, text):
    return acct.sign_message(encode_defunct(text=text)).signature.to_0x_hex()


def test_linking_needs_a_comfy_launch_and_the_creators_signature(svc):
    msg = svc.link_token_message(AGENT.address, TOKEN)
    assert TOKEN in msg and AGENT.address.lower() in msg and "16602" in msg
    with pytest.raises(LoreError, match="wasn't launched on comfy"):
        svc.link_token(PERSON, "0x" + "99" * 20, sign(CREATOR, msg))
    with pytest.raises(LoreError, match="wallet that launched"):
        svc.link_token(PERSON, TOKEN, sign(AGENT, msg))  # not the creator: can't claim someone else's token
    other = svc.link_token_message("0x" + "12" * 20, TOKEN)
    with pytest.raises(LoreError, match="wallet that launched"):
        svc.link_token(PERSON, TOKEN, sign(CREATOR, other))  # a signature for another agent can't be reused
    out = svc.link_token(PERSON, TOKEN, sign(CREATOR, msg))
    assert out["pool_id"] == POOL
    assert svc.chain.sent[-1] == ("AuthorTokens", "link", AGENT.address, bytes.fromhex(POOL[2:]))


def test_no_author_token_no_submission(svc):
    svc.chain.tokenless = {AGENT.address.lower()}
    with pytest.raises(LoreError, match="comfy token"):
        svc.prepare_submit(PERSON, "some research")
    assert svc.storage.blobs == {}  # refused before anything was uploaded


def test_bought_tokens_are_listed_and_only_unlocked_ones_claimed(svc):
    locked, ready = "0x" + "a1" * 20, "0x" + "b2" * 20
    a = AGENT.address.lower()
    svc.chain.locks = {(a, locked): {"amount": 5, "unlock_at": 2_000}, (a, ready): {"amount": 7, "unlock_at": 500}}
    with svc.tx() as conn:
        conn.execute("INSERT INTO purchases VALUES (1, ?)", (a,))
    locks = {lk["token"]: lk for lk in svc.my_tokens(PERSON)["locks"]}
    assert locks[locked]["claimable"] is False and locks[ready]["claimable"] is True
    txs = svc.prepare_claim_tokens(PERSON)["transactions"]
    assert [(t["description"], t["args"][0].lower()) for t in txs] == [("LockVault.claim", ready)]
    svc.chain.locks = {(a, locked): {"amount": 5, "unlock_at": 2_000}}
    with pytest.raises(LoreError, match="unlocked yet"):
        svc.prepare_claim_tokens(PERSON)
