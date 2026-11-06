import sqlite3

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS seen        (block INT, idx INT, PRIMARY KEY (block, idx));
CREATE TABLE IF NOT EXISTS cursor      (k TEXT PRIMARY KEY, v INT);
CREATE TABLE IF NOT EXISTS topics      (id INT PRIMARY KEY, meta_hash TEXT, meta_json TEXT);
CREATE TABLE IF NOT EXISTS nodes       (id INT PRIMARY KEY, topic_id INT, contributor TEXT,
                                        content_hash TEXT, storage_root TEXT, meta_hash TEXT, meta_json TEXT);
CREATE TABLE IF NOT EXISTS edges       (child INT, parent INT, PRIMARY KEY (child, parent));
CREATE TABLE IF NOT EXISTS submissions (id INT PRIMARY KEY, topic_id INT, submitter TEXT, content_hash TEXT,
                                        storage_root TEXT, status TEXT, passed INT, parents TEXT,
                                        report_hash TEXT, eligible INT, reported_at INT, node_id INT,
                                        submitted_at INT);
CREATE TABLE IF NOT EXISTS votes       (sub_id INT, voter TEXT, approve INT, person TEXT, PRIMARY KEY (sub_id, voter));
CREATE TABLE IF NOT EXISTS persons     (agent TEXT PRIMARY KEY, person TEXT);
CREATE TABLE IF NOT EXISTS purchases   (topic_id INT, buyer TEXT, PRIMARY KEY (topic_id, buyer));
CREATE TABLE IF NOT EXISTS reports     (id INT PRIMARY KEY, topic_id INT, reporter TEXT, evidence_hash TEXT,
                                        matched_wallet TEXT, score_bps INT, matched_ref TEXT);
CREATE TABLE IF NOT EXISTS ingests     (content_hash TEXT PRIMARY KEY, caller TEXT, storage_root TEXT, topic_id INT,
                                        ingested_at INT);
-- Every watermarked copy handed out: ref is node:<id> (a buyer's node) or sub:<id> (a voter's task).
CREATE TABLE IF NOT EXISTS deliveries  (topic_id INT, wallet TEXT, ref TEXT, PRIMARY KEY (topic_id, wallet, ref));
CREATE TABLE IF NOT EXISTS evidence    (hash TEXT PRIMARY KEY, topic_id INT, text TEXT);
-- Hosted MCP login: OAuth 2.1 with World ID (gateway/oauth.py). person = World ID nullifier.
CREATE TABLE IF NOT EXISTS oauth_clients (client_id TEXT PRIMARY KEY, info TEXT, created INT);
CREATE TABLE IF NOT EXISTS oauth_pending (id TEXT PRIMARY KEY, client_id TEXT, params TEXT, expires INT);
CREATE TABLE IF NOT EXISTS oauth_codes   (code TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS oauth_tokens  (token TEXT PRIMARY KEY, kind TEXT, client_id TEXT, person TEXT, scopes TEXT,
                                          expires INT, resource TEXT);
-- Wallets Lore created on Turnkey with delegated access (gateway/turnkey.py).
CREATE TABLE IF NOT EXISTS turnkey_wallets (person TEXT PRIMARY KEY, email TEXT, created_ms INT,  -- one wallet a person
                                            address TEXT UNIQUE, sub_org TEXT, ready INT NOT NULL DEFAULT 0);
-- What each sale paid (Royalties.Distributed): prices depend on the topic's size at the time of sale.
CREATE TABLE IF NOT EXISTS sales         (block INT, idx INT, topic_id INT, amount INT, PRIMARY KEY (block, idx));
-- World ID Agent Pass (gateway/worldidp.py): one row per OIDC attempt; state/nonce/PKCE verifier never leave us.
CREATE TABLE IF NOT EXISTS idp_attempts  (state TEXT PRIMARY KEY, nonce TEXT, verifier TEXT, purpose TEXT, pending TEXT,
                                          checkpoint TEXT, created INT);
-- Human checkpoints: an agent action Lore will only sign after a fresh World ID approval by the same person.
CREATE TABLE IF NOT EXISTS checkpoints   (id TEXT PRIMARY KEY, person TEXT, action TEXT, prepared TEXT, status TEXT,
                                          created INT, decided INT, reason TEXT, tx_hashes TEXT);
-- What each person has already been told about (lore_inbox).
CREATE TABLE IF NOT EXISTS inbox_state   (person TEXT PRIMARY KEY, since_node INT, subs TEXT);
"""


SCHEMA_VERSION = 7  # bump whenever a table changes shape


def bind_deployment(db, deployment: str) -> None:
    """Fail fast if this gateway database was built for another deployment or an older schema."""
    from dbguard import bind

    bind(db, deployment, SCHEMA_VERSION, "SELECT 1 FROM seen LIMIT 1")


def connect(path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI runs a dependency and its endpoint on different threadpool
    # threads. Each connection is still used by one request (or the worker) only.
    db = sqlite3.connect(path, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def synced_block(db) -> int:
    row = db.execute("SELECT v FROM cursor WHERE k='block'").fetchone()
    return row[0] if row else -1
