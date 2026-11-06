// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Default values from BUILD_PLAN.md section 3.1, mirrored in packages/shared/src/constants.js.
/// @dev These are only the initial values. Every on-chain one is stored in its contract and
///      settable by ADMIN, so changing a value never needs a redeploy. USDC has 6 decimals.
library Constants {
    uint256 internal constant STAKE = 10_000000; // 10 USDC
    uint256 internal constant STAKE_FEE = 500000; // 0.5 USDC
    uint256 internal constant TOPIC_PRICE = 5_000000; // 5 USDC
    uint256 internal constant PLATFORM_CUT_BPS = 1000; // 10%
    uint256 internal constant SLASH_TO_VOTERS_BPS = 5000; // 50%
    uint256 internal constant VOTING_WINDOW = 24 hours;
    uint256 internal constant QUORUM_BPS = 5000; // 50% of eligible contributors
    uint256 internal constant MAX_PARENTS = 5;

    // Off-chain only (enforced by the verifier agent); kept here so both copies stay in sync.
    uint256 internal constant MIN_CHARS = 500;
    uint256 internal constant MAX_CHARS = 50_000;
    uint256 internal constant DUP_SIMILARITY_BPS = 9200; // 0.92 cosine
    uint256 internal constant EDGE_SIMILARITY_BPS = 7500; // 0.75 hybrid score

    uint256 internal constant BPS = 10_000;
}
