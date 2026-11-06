// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC1155} from "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {IAccess} from "./interfaces/ILore.sol";
import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";
import {TopicGraph} from "./TopicGraph.sol";
import {Royalties} from "./Royalties.sol";
import {Constants} from "./Constants.sol";

/// @notice Soulbound ERC-1155 access pass, token id = topicId. Buying is the only way to get access.
///         Access is permanent and covers nodes added to the topic later.
contract Access is IAccess, ERC1155, LoreBase {
    using SafeERC20 for IERC20;

    IERC20 public immutable usdc;
    TopicGraph public immutable graph;
    Royalties public immutable royalties;
    /// @notice What one node is worth, in USDC (6 decimals): roughly the model tokens a buyer saves by not redoing
    ///         that research. A topic costs nodeValue x its accepted nodes, so each node earns the same per sale.
    uint256 public nodeValue = Constants.NODE_VALUE;

    event NodeValueSet(uint256 value);

    error Soulbound();
    error Banned(address wallet);
    error AlreadyHeld(uint256 topicId);
    error UnknownTopic(uint256 topicId);

    constructor(LoreRoles roles_, IERC20 usdc_, TopicGraph graph_, Royalties royalties_)
        ERC1155("")
        LoreBase(roles_)
    {
        if (address(usdc_) == address(0) || address(graph_) == address(0) || address(royalties_) == address(0)) {
            revert ZeroAddress();
        }
        usdc = usdc_;
        graph = graph_;
        royalties = royalties_;
    }

    function setNodeValue(uint256 value) external onlyAdmin {
        nodeValue = value;
        emit NodeValueSet(value);
    }

    /// @inheritdoc IAccess
    function priceOf(uint256 topicId) public view returns (uint256) {
        return nodeValue * graph.nodeCount(topicId);
    }

    function setURI(string calldata newuri) external onlyAdmin {
        _setURI(newuri);
    }

    /// @inheritdoc IAccess
    function buy(uint256 topicId) external {
        if (!graph.topicExists(topicId)) revert UnknownTopic(topicId);
        if (balanceOf(msg.sender, topicId) != 0) revert AlreadyHeld(topicId);
        if (graph.registry().isBanned(msg.sender)) revert Banned(msg.sender);

        uint256 price = priceOf(topicId);
        usdc.safeTransferFrom(msg.sender, address(royalties), price);
        royalties.distribute(topicId, price);

        // Mint last: the balance is set before the ERC1155 receiver hook runs, so a re-entrant buy hits AlreadyHeld.
        _mint(msg.sender, topicId, 1, "");
        emit Bought(topicId, msg.sender);
    }

    /// @inheritdoc IAccess
    function hasAccess(uint256 topicId, address a) external view returns (bool) {
        return balanceOf(a, topicId) != 0 && !graph.registry().isBanned(a);
    }

    // ---------- soulbound ----------

    /// @dev Minting (from == 0) is the only allowed balance change. Transfers and burns revert.
    function _update(address from, address to, uint256[] memory ids, uint256[] memory values) internal override {
        if (from != address(0)) revert Soulbound();
        super._update(from, to, ids, values);
    }

    function setApprovalForAll(address, bool) public pure override {
        revert Soulbound();
    }
}
