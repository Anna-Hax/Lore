# ponytail: temporary mirror of BUILD_PLAN §3.1's off-chain values. Delete once P3's lore_shared.constants lands.
# On-chain values (stake, price, voting window, quorum) are read from P2's contracts, never from here.
MIN_CHARS, MAX_CHARS = 500, 50_000
DUP_SIMILARITY = 0.92
EDGE_SIMILARITY = 0.75
MAX_PARENTS = 5
# ponytail: placeholder; P3 tunes it to the real watermark's false-positive rate.
MIN_LEAK_SCORE_BPS = 7000  # below this, a leak report is not pinned on anyone on-chain
