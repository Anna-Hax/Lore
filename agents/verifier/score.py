"""Pure scoring for the verifier (BUILD_PLAN.md §4 D, steps 3, 4 and 6).

Thresholds are passed in by the caller from lore_shared.constants.
"""

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[^\W_]{3,}")


def length_ok(text: str, lo: int, hi: int) -> bool:
    return lo <= len(text) <= hi


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.hypot(*a), math.hypot(*b)
    return dot / (na * nb) if na and nb else 0.0


def find_duplicate(vec, candidates, threshold):
    """Closest candidate scoring >= threshold, as (id, score), or None.

    The caller passes accepted nodes plus pending submissions with a smaller
    subId, which is how "the earlier submission wins" is enforced.
    candidates: iterable of (id, vec).
    """
    best = None
    for cid, cvec in candidates:
        s = cosine(vec, cvec)
        if s >= threshold and (best is None or s > best[1]):
            best = (cid, s)
    return best


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def bm25(query: str, docs: dict[str, str], k1: float = 1.2, b: float = 0.75) -> dict[str, float]:
    """BM25 of `query` against each doc, normalised so the best doc scores 1."""
    toks = {d: _tokens(t) for d, t in docs.items()}
    avg = sum(map(len, toks.values())) / (len(toks) or 1)
    df = Counter(w for t in toks.values() for w in set(t))
    terms = set(_tokens(query))
    raw = {}
    for d, t in toks.items():
        tf = Counter(t)
        raw[d] = sum(
            math.log(1 + (len(docs) - df[w] + 0.5) / (df[w] + 0.5))
            * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
            for w in terms if tf[w]
        )
    top = max(raw.values(), default=0)
    return {d: (s / top if top else 0.0) for d, s in raw.items()}


def suggest_parents(text, vec, nodes, threshold, max_parents, w_cos=0.7):
    """Parent edges: w_cos*cosine + (1-w_cos)*bm25, keep >= threshold, best first, at most max_parents.

    nodes: dict node_id -> (text, vec) of the topic's accepted nodes.
    An empty list means the submission becomes a new top-level node.
    """
    kw = bm25(text, {n: t for n, (t, _) in nodes.items()})
    scored = [
        {"node_id": n, "score": w_cos * cosine(vec, v) + (1 - w_cos) * kw[n]}
        for n, (_, v) in nodes.items()
    ]
    scored = [p for p in scored if p["score"] >= threshold]
    return sorted(scored, key=lambda p: -p["score"])[:max_parents]
