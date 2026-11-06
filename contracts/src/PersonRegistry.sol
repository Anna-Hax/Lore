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

    event AgentRegistered(address indexed agent, bytes32 indexed person);

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
}
