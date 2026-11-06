"""Configurable v1 placeholders; token amounts are integer USDC micro-units."""

from dataclasses import dataclass

STAKE = 10_000_000
STAKE_FEE = 500_000
TOPIC_PRICE = 5_000_000
PLATFORM_CUT_BPS = 1_000
SLASH_TO_VOTERS_BPS = 5_000
VOTING_WINDOW = 24 * 60 * 60
QUORUM_BPS = 5_000
MIN_CHARS = 500
MAX_CHARS = 50_000
DUP_SIMILARITY = 0.92
EDGE_SIMILARITY = 0.75
MAX_PARENTS = 5


@dataclass(frozen=True)
class Constants:
    """Override at application startup to match the deployed contracts."""

    STAKE: int = STAKE
    STAKE_FEE: int = STAKE_FEE
    TOPIC_PRICE: int = TOPIC_PRICE
    PLATFORM_CUT_BPS: int = PLATFORM_CUT_BPS
    SLASH_TO_VOTERS_BPS: int = SLASH_TO_VOTERS_BPS
    VOTING_WINDOW: int = VOTING_WINDOW
    QUORUM_BPS: int = QUORUM_BPS
    MIN_CHARS: int = MIN_CHARS
    MAX_CHARS: int = MAX_CHARS
    DUP_SIMILARITY: float = DUP_SIMILARITY
    EDGE_SIMILARITY: float = EDGE_SIMILARITY
    MAX_PARENTS: int = MAX_PARENTS
