// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {LoreRoles} from "./LoreRoles.sol";

/// @notice Shared role checks against the single LoreRoles contract.
abstract contract LoreBase {
    LoreRoles public immutable roles;

    error NotAuthorized();
    error ZeroAddress();
    error InvalidParam();

    constructor(LoreRoles roles_) {
        if (address(roles_) == address(0)) revert ZeroAddress();
        roles = roles_;
    }

    modifier onlyRole(bytes32 role) {
        _checkRole(role);
        _;
    }

    modifier onlyAdmin() {
        _checkRole(roles.ADMIN_ROLE());
        _;
    }

    function _checkRole(bytes32 role) internal view {
        if (!roles.hasRole(role, msg.sender)) revert NotAuthorized();
    }

    function _treasury() internal view returns (address) {
        return roles.treasury();
    }
}
