// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";
import {IComfyPoolManager, PoolKey} from "./interfaces/IComfy.sol";

/// @notice Every author (agent wallet) must have a comfy token before it can submit. Topic buyers receive the
///         authors' tokens, bought on comfy in the same purchase (Access.buy).
/// @dev The gateway, as REGISTRAR, links a token only after checking off-chain that the agent's person controls the
///      wallet that launched it on comfy (a signature from the creator in comfy's `Launched` event). The pool key is
///      read from comfy's pool manager here, so Access always swaps on the pool the token really trades in.
contract AuthorTokens is LoreBase {
    IComfyPoolManager public immutable poolManager;
    mapping(address => PoolKey) private _keys;

    event Linked(address indexed agent, address indexed token, bytes32 poolId);

    error NotAComfyPool(bytes32 poolId);

    constructor(LoreRoles roles_, IComfyPoolManager poolManager_) LoreBase(roles_) {
        if (address(poolManager_) == address(0)) revert ZeroAddress();
        poolManager = poolManager_;
    }

    /// @notice Link (or relink) `agent` to the comfy token traded in pool `poolId`.
    function link(address agent, bytes32 poolId) external onlyRole(roles.REGISTRAR_ROLE()) {
        if (agent == address(0)) revert ZeroAddress();
        (address c0, address c1, address hooks, address pm, uint24 fee, bytes32 params) = poolManager.poolIdToPoolKey(poolId);
        if (c0 != address(0) || c1 == address(0)) revert NotAComfyPool(poolId); // native 0G / launch token only
        _keys[agent] = PoolKey(c0, c1, hooks, pm, fee, params);
        emit Linked(agent, c1, poolId);
    }

    function tokenOf(address agent) external view returns (address) {
        return _keys[agent].currency1;
    }

    function keyOf(address agent) external view returns (PoolKey memory) {
        return _keys[agent];
    }
}
