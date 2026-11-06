"""Lore's verifier (BUILD_PLAN §4 D).

`verify` judges one submission and returns what to post on-chain. Its outside
world is injected so it runs today against fakes and later against the real thing:
    gw           gwclient.Gateway (plaintext + candidates)
    embed        text -> vector (TeeML model or local, decided by spike S)
    llm          (messages, prompt_version) -> (output, receipt); zg.call with model/key bound
    upload_json  dict -> 0G Storage root (P3's lore_shared.storage)
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import zg
from jobs import NotReady, Skip, loop
from lore_shared.constants import DUP_SIMILARITY, EDGE_SIMILARITY, MAX_CHARS, MAX_PARENTS, MIN_CHARS
from verifier.score import cosine, find_duplicate, length_ok, suggest_parents

PROMPT_VERSION = "verify_v2"
SYSTEM = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()
CHECKS = ("ingested_by_gateway", "length", "original_vs_graph", "original_vs_pending",
          "relevant", "fits_topic", "original_vs_public")
log = logging.getLogger("lore.verifier")


def verify(sub_id: int, *, gw, embed, llm, upload_json, min_block: int = 0) -> dict:
    """Return {"passed", "parents", "report_root", "report"} for one submission."""
    checks = dict.fromkeys(CHECKS, False)
    reasons, receipts, parents, best = [], [], [], {"score": 0.0}
    verdict_receipt = None  # the receipt whose signed output produced the checks (None if no verdict)
    p = gw.plaintext("sub", sub_id)
    if p["synced_block"] < min_block:
        raise NotReady(f"gateway at block {p['synced_block']}, need {min_block}")
    if p["status"] != "Pending":  # already reported or finalized (e.g. after a restart): never pay twice
        raise Skip(f"submission {sub_id} is {p['status']}")
    topic_id = p["topic_id"]

    def done():
        report = {
            "sub_id": str(sub_id), "topic_id": str(topic_id), "passed": all(checks.values()),
            "checks": checks, "max_similarity": best, "parents": parents, "reasons": reasons,
            "receipts": receipts, "verdict_receipt": verdict_receipt, "created_at": datetime.now(UTC).isoformat(),
        }
        return {"passed": report["passed"], "parents": [int(x["node_id"]) for x in parents],
                "report_root": upload_json(report), "report": report}

    checks["ingested_by_gateway"] = p["ingested"]
    if not p["ingested"]:
        reasons.append("Not submitted through Lore's gateway, so it skipped the vote-before-submit gate.")
        return done()

    text = p["text"]
    checks["length"] = length_ok(text, MIN_CHARS, MAX_CHARS)
    if not checks["length"]:
        reasons.append(f"Length {len(text)} is outside the allowed {MIN_CHARS}-{MAX_CHARS} characters.")
        return done()

    c = gw.candidates(topic_id)
    vec = embed(text)
    nodes = {n["node_id"]: (n["text"], embed(n["text"])) for n in c["nodes"]}
    titles = {n["node_id"]: (n["meta"] or {}).get("title", f"node {n['node_id']}") for n in c["nodes"]}
    earlier = [(f"sub:{s['sub_id']}", embed(s["text"])) for s in c["pending"] if s["sub_id"] < sub_id]
    graph = [(f"node:{k}", v) for k, (_, v) in nodes.items()]

    closest = find_duplicate(vec, graph + earlier, -1.0)
    if closest:
        best = {"id": closest[0], "score": round(closest[1], 4)}
    dup_graph = find_duplicate(vec, graph, DUP_SIMILARITY)
    dup_pending = find_duplicate(vec, earlier, DUP_SIMILARITY)
    checks["original_vs_graph"], checks["original_vs_pending"] = dup_graph is None, dup_pending is None
    if dup_graph or dup_pending:
        hit = dup_graph or dup_pending
        reasons.append(f"Near-duplicate of {hit[0]} (similarity {hit[1]:.2f}); the earlier one takes priority.")
        return done()

    nearest = sorted(nodes, key=lambda k: -cosine(vec, nodes[k][1]))[:5]
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps({
            # null only for a new topic; an existing topic without a summary yet still says "existing"
            "topic": {k: (c["topic"] or {}).get(k) for k in ("title", "description")} if topic_id else None,
            "closest_nodes": [titles[k] for k in nearest],
            "submission": text,
        }, ensure_ascii=False)},
    ]
    verdict = None
    for _ in range(2):  # one retry: the router may pick another provider, so output can differ
        out, receipt = llm(messages, PROMPT_VERSION)
        receipts.append(upload_json(receipt))
        try:
            v = zg.json_out(out)
            verdict = {k: v[k] is True for k in ("relevant", "fits_topic", "original_vs_public")}
            reasons.extend(str(r) for r in v.get("reasons", [])[:3])
            verdict_receipt = receipts[-1]
            break
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    if verdict:
        checks.update(verdict)
    else:
        # Fail closed with a reason voters can see; on an existing topic, voters can still override this.
        reasons.append("The verifier model did not return a usable verdict, so the checks fail closed.")

    if topic_id:
        parents = suggest_parents(text, vec, nodes, EDGE_SIMILARITY, MAX_PARENTS)
    return done()


def run(chain, jobs, *, gw, embed, llm, upload_json, start_block: int, every: int = 10, once: bool = False):
    """Verify every Submitted event and post its report. State lives in `jobs` (survives restarts).

    Each result is saved before it is posted, so a failed or timed-out postReport is resent as is:
    the paid model calls happen once per submission.
    """
    jobs.db.execute("CREATE TABLE IF NOT EXISTS results (sub_id INT PRIMARY KEY, passed INT, parents TEXT, report_root TEXT)")

    def handle(sub_id, block):
        if chain.submission_status(sub_id) != "Pending":  # the chain is the authority; never pay twice
            raise Skip(f"submission {sub_id} already reported")
        saved = jobs.db.execute("SELECT * FROM results WHERE sub_id=?", (sub_id,)).fetchone()
        if saved is None:
            r = verify(sub_id, gw=gw, embed=embed, llm=llm, upload_json=upload_json, min_block=block)
            with jobs.db:
                jobs.db.execute("INSERT INTO results VALUES (?, ?, ?, ?)",
                                (sub_id, int(r["passed"]), json.dumps(r["parents"]), r["report_root"]))
            saved = jobs.db.execute("SELECT * FROM results WHERE sub_id=?", (sub_id,)).fetchone()
        passed, parents = bool(saved["passed"]), json.loads(saved["parents"])
        chain.send("Submissions", "postReport", sub_id, passed, parents,
                   bytes.fromhex(saved["report_root"].removeprefix("0x")))
        log.info("sub %s: passed=%s parents=%s", sub_id, passed, parents)

    loop(jobs, chain, event="Submitted", key="subId", start_block=start_block, handle=handle, every=every, once=once)
