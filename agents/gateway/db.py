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
CREATE TABLE IF NOT EXISTS nonces      (message TEXT PRIMARY KEY, address TEXT, expires INT);
CREATE TABLE IF NOT EXISTS tokens      (token TEXT PRIMARY KEY, address TEXT, expires INT);
"""


SCHEMA_VERSION = 3  # bump whenever a table changes shape


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
