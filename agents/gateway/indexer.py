"""Turns chain events into gateway rows (BUILD_PLAN §4 B, step 1).

`apply` is idempotent: each (block, log_index) is applied at most once.
Addresses are stored lowercase; hashes and roots as 0x-hex.
"""

import json

from chain import hexstr


def apply(db, event: str, a: dict, block: int, idx: int, ts: int) -> None:
    """Apply one event inside the caller's transaction."""
    if db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (block, idx)).rowcount == 0:
        return
    q = db.execute
    match event:
        case "TopicCreated":
            q("INSERT OR IGNORE INTO topics (id) VALUES (?)", (a["topicId"],))
        case "NodeAdded":
            q("INSERT OR IGNORE INTO nodes (id, topic_id, contributor) VALUES (?, ?, ?)",
              (a["nodeId"], a["topicId"], a["contributor"].lower()))
            q("INSERT OR IGNORE INTO topics (id) VALUES (?)", (a["topicId"],))
            for p in a["parents"]:
                q("INSERT OR IGNORE INTO edges VALUES (?, ?)", (a["nodeId"], p))
        case "Submitted":
            q("INSERT OR IGNORE INTO submissions (id, topic_id, submitter, content_hash, storage_root, status, submitted_at)"
              " VALUES (?, ?, ?, ?, ?, 'Pending', ?)",
              (a["subId"], a["topicId"], a["submitter"].lower(), hexstr(a["contentHash"]), hexstr(a["storageRoot"]), ts))
        case "Reported":
            q("UPDATE submissions SET status='Reported', passed=?, parents=?, report_hash=?, eligible=?, reported_at=?"
              " WHERE id=?",
              (int(a["pass"]), json.dumps(list(a["parents"])), hexstr(a["reportHash"]), a["eligibleVoters"], ts, a["subId"]))
        case "Voted":
            q("INSERT OR IGNORE INTO votes VALUES (?, ?, ?, ?)",
              (a["subId"], a["voter"].lower(), int(a["approve"]), hexstr(a["person"])))
        case "Finalized":
            q("UPDATE submissions SET status=?, node_id=? WHERE id=?",
              ("Accepted" if a["accepted"] else "Rejected", a["nodeId"] if a["accepted"] else None, a["subId"]))
            if a["accepted"]:  # NodeAdded came earlier in the same tx; copy the content pointers onto the node
                q("UPDATE nodes SET (content_hash, storage_root) ="
                  " (SELECT content_hash, storage_root FROM submissions WHERE id=?) WHERE id=?",
                  (a["subId"], a["nodeId"]))
        case "NodeMetaSet":
            q("UPDATE nodes SET meta_hash=?, meta_json=NULL WHERE id=?", (hexstr(a["metaHash"]), a["nodeId"]))
        case "TopicMetaSet":
            q("UPDATE topics SET meta_hash=?, meta_json=NULL WHERE id=?", (hexstr(a["metaHash"]), a["topicId"]))
        case "Distributed":
            q("INSERT OR IGNORE INTO sales VALUES (?, ?, ?, ?)", (block, idx, a["topicId"], a["amount"]))
        case "Bought":
            q("INSERT OR IGNORE INTO purchases VALUES (?, ?)", (a["topicId"], a["buyer"].lower()))
        case "LeakReported":
            q("INSERT OR IGNORE INTO reports (id, topic_id, reporter, evidence_hash) VALUES (?, ?, ?, ?)",
              (a["reportId"], a["topicId"], a["reporter"].lower(), hexstr(a["evidenceHash"])))
        case "AgentRegistered":
            q("INSERT OR IGNORE INTO persons VALUES (?, ?)", (a["agent"].lower(), hexstr(a["person"])))
        case "LeakMatched":
            q("UPDATE reports SET matched_wallet=?, score_bps=? WHERE id=?",
              (a["wallet"].lower(), a["scoreBps"], a["reportId"]))
