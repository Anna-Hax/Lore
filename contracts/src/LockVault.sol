// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";
import {Constants} from "./Constants.sol";

/// @notice Holds the author tokens a topic buyer received until `lockPeriod` has passed, so nobody can buy a topic
///         and sell its tokens straight back (which would make access nearly free and pay authors nothing).
contract LockVault is LoreBase {
    using SafeERC20 for IERC20;

    struct Lock {
        uint256 amount;
        uint64 unlockAt;
    }

    address public access;
    uint256 public lockPeriod = Constants.LOCK_PERIOD;
    mapping(address => mapping(address => Lock)) public locks; // owner => token => lock

    event AccessSet(address access);
    event LockPeriodSet(uint256 lockPeriod);
    event Credited(address indexed owner, address indexed token, uint256 amount, uint64 unlockAt);
    event Claimed(address indexed owner, address indexed token, uint256 amount);

    error Locked(uint64 unlockAt);
    error NothingToClaim();

    constructor(LoreRoles roles_) LoreBase(roles_) {}

    function setAccess(address a) external onlyAdmin {
        if (a == address(0)) revert ZeroAddress();
        access = a;
        emit AccessSet(a);
    }

    function setLockPeriod(uint256 p) external onlyAdmin {
        lockPeriod = p;
        emit LockPeriodSet(p);
    }

    /// @notice Access calls this after comfy delivered `amount` of `token` to this vault for `owner`.
    /// @dev ponytail: one lock per owner and token, so a later purchase of the same author's token restarts the
    ///      clock for the whole balance. Per-purchase lots if buyers object.
    function credit(address owner, address token, uint256 amount) external {
        if (msg.sender != access) revert NotAuthorized();
        Lock storage l = locks[owner][token];
        l.amount += amount;
        l.unlockAt = uint64(block.timestamp + lockPeriod);
        emit Credited(owner, token, amount, l.unlockAt);
    }

    /// @notice Withdraw your unlocked `token` balance. Only ever to the owner itself.
    function claim(address token) external {
        Lock memory l = locks[msg.sender][token];
        if (l.amount == 0) revert NothingToClaim();
        if (block.timestamp < l.unlockAt) revert Locked(l.unlockAt);
        delete locks[msg.sender][token];
        IERC20(token).safeTransfer(msg.sender, l.amount);
        emit Claimed(msg.sender, token, l.amount);
    }
}
