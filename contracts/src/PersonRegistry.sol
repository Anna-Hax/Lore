// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";

/// @notice Links agents to the real person (World ID) behind them. One person can run many agents;
///         Submissions gives each person one vote, whichever of their agents casts it.
/// @dev World ID can't be verified on 0G, so the gateway (REGISTRAR) checks each proof off-chain with World's
///      API, using the agent's address as the signal, and records the result here. `person` is the World ID
///      nullifier for Lore's action: the same for every agent of one human, different across humans.
contract PersonRegistry is LoreBase {
    mapping(address => bytes32) public personOf;
    /// @notice A person removed from Lore (a proven leaker). Covers every wallet they have or link later.
    mapping(bytes32 => bool) public bannedPerson;
    /// @notice A wallet removed from Lore that was never linked to a person.
    mapping(address => bool) public bannedWallet;

    event AgentRegistered(address indexed agent, bytes32 indexed person);
    event Banned(address indexed wallet, bytes32 indexed person);

    error AlreadyRegistered(address agent);

    constructor(LoreRoles roles_) LoreBase(roles_) {}

    function register(address agent, bytes32 person) external onlyRole(roles.REGISTRAR_ROLE()) {
        if (agent == address(0) || person == bytes32(0)) revert InvalidParam();
        bytes32 current = personOf[agent];
        if (current == person) return; // idempotent: a retried registration is fine
        if (current != bytes32(0)) revert AlreadyRegistered(agent); // an agent never changes owner
        personOf[agent] = person;
        emit AgentRegistered(agent, person);
    }

    /// @notice Remove the person behind `wallet` (or the bare wallet) from Lore: no buying, no reading, no
    ///         submitting, no voting, on every topic. Called by the leak detector once a leak is proven.
    function ban(address wallet) external onlyRole(roles.LEAK_DETECTOR_ROLE()) {
        if (wallet == address(0)) revert InvalidParam();
        bytes32 person = personOf[wallet];
        if (person != bytes32(0)) bannedPerson[person] = true;
        else bannedWallet[wallet] = true;
        emit Banned(wallet, person);
    }

    /// @notice True if `wallet`, or the person it belongs to, is removed from Lore.
    function isBanned(address wallet) public view returns (bool) {
        bytes32 person = personOf[wallet];
        return bannedWallet[wallet] || (person != bytes32(0) && bannedPerson[person]);
    }
}
