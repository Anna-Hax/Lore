// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @notice Single source of roles for every Lore contract.
/// @dev ADMIN is OZ's DEFAULT_ADMIN_ROLE, so it can grant and revoke every other role.
///      TREASURY is an address, not a role: it receives fees, rejected stakes and the platform cut.
contract LoreRoles is AccessControl {
    bytes32 public constant ADMIN_ROLE = DEFAULT_ADMIN_ROLE;
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER");
    bytes32 public constant CURATOR_ROLE = keccak256("CURATOR");
    bytes32 public constant LEAK_DETECTOR_ROLE = keccak256("LEAK_DETECTOR");
    /// @notice The gateway: records agent -> person after checking a World ID proof.
    bytes32 public constant REGISTRAR_ROLE = keccak256("REGISTRAR");

    address public treasury;

    event TreasurySet(address indexed treasury);

    error ZeroAddress();

    constructor(address admin, address treasury_) {
        if (admin == address(0) || treasury_ == address(0)) revert ZeroAddress();
        _grantRole(ADMIN_ROLE, admin);
        treasury = treasury_;
        emit TreasurySet(treasury_);
    }

    function setTreasury(address treasury_) external onlyRole(ADMIN_ROLE) {
        if (treasury_ == address(0)) revert ZeroAddress();
        treasury = treasury_;
        emit TreasurySet(treasury_);
    }

    function isAdmin(address a) external view returns (bool) {
        return hasRole(ADMIN_ROLE, a);
    }

    function isVerifier(address a) external view returns (bool) {
        return hasRole(VERIFIER_ROLE, a);
    }

    function isCurator(address a) external view returns (bool) {
        return hasRole(CURATOR_ROLE, a);
    }

    function isLeakDetector(address a) external view returns (bool) {
        return hasRole(LEAK_DETECTOR_ROLE, a);
    }

    function isRegistrar(address a) external view returns (bool) {
        return hasRole(REGISTRAR_ROLE, a);
    }
}
