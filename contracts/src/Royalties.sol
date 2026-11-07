// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Address} from "@openzeppelin/contracts/utils/Address.sol";
import {IRoyalties} from "./interfaces/ILore.sol";
import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";
import {TopicGraph} from "./TopicGraph.sol";
import {Constants} from "./Constants.sol";

/// @notice Splits each sale: platform cut to treasury, the rest equally across the topic's nodes.
/// @dev MasterChef-style accumulator in native 0G wei (no scaling): accPerNode[topic] only grows,
///      and a node's debt is set to the accumulator when it's accepted, so it earns only from later sales.
///      Because every share is an exact integer, the contract never owes more than it holds;
///      the per-sale remainder (dust) goes to treasury.
contract Royalties is IRoyalties, LoreBase {
    TopicGraph public immutable graph;
    address public access;
    uint256 public platformCutBps = Constants.PLATFORM_CUT_BPS;

    mapping(uint256 => uint256) public accPerNode; // topicId => cumulative 0G (wei) per node
    mapping(uint256 => uint256) public debt; // nodeId => accPerNode at accept time, or at last claim

    event AccessSet(address access);
    event PlatformCutSet(uint256 bps);
    event Distributed(uint256 indexed topicId, uint256 amount, uint256 perNode, uint256 toTreasury);
    event Claimed(address indexed contributor, uint256 indexed nodeId, uint256 amount);

    error NotContributor(uint256 nodeId);
    error EmptyTopic(uint256 topicId);
    error WrongAmount(uint256 amount, uint256 sent);

    constructor(LoreRoles roles_, TopicGraph graph_) LoreBase(roles_) {
        if (address(graph_) == address(0)) revert ZeroAddress();
        graph = graph_;
    }

    // ---------- wiring / admin ----------

    function setAccess(address a) external onlyAdmin {
        if (a == address(0)) revert ZeroAddress();
        access = a;
        emit AccessSet(a);
    }

    function setPlatformCutBps(uint256 bps) external onlyAdmin {
        if (bps > Constants.BPS) revert InvalidParam();
        platformCutBps = bps;
        emit PlatformCutSet(bps);
    }

    // ---------- hooks ----------

    /// @notice Called by TopicGraph when a node is accepted. The node starts with zero claimable.
    function onNodeAdded(uint256 topicId, uint256 nodeId) external {
        if (msg.sender != address(graph)) revert NotAuthorized();
        debt[nodeId] = accPerNode[topicId];
    }

    /// @inheritdoc IRoyalties
    /// @dev Access sends exactly `amount` 0G with the call.
    function distribute(uint256 topicId, uint256 amount) external payable {
        if (msg.sender != access) revert NotAuthorized();
        if (msg.value != amount) revert WrongAmount(amount, msg.value);
        uint256 n = graph.nodeCount(topicId);
        if (n == 0) revert EmptyTopic(topicId);

        uint256 cut = amount * platformCutBps / Constants.BPS;
        uint256 perNode = (amount - cut) / n;
        uint256 toTreasury = amount - perNode * n; // platform cut + rounding dust
        accPerNode[topicId] += perNode;

        if (toTreasury > 0) Address.sendValue(payable(_treasury()), toTreasury);
        emit Distributed(topicId, amount, perNode, toTreasury);
    }

    /// @inheritdoc IRoyalties
    function claimable(uint256 nodeId) public view returns (uint256) {
        if (!graph.nodeExists(nodeId)) return 0;
        (uint256 topicId,,,,,) = graph.nodes(nodeId);
        return accPerNode[topicId] - debt[nodeId];
    }

    /// @notice Total claimable for `nodeIds`, for the gateway's `lore_claimable` tool.
    function claimableMany(uint256[] calldata nodeIds) external view returns (uint256 total) {
        for (uint256 i; i < nodeIds.length; ++i) {
            total += claimable(nodeIds[i]);
        }
    }

    /// @inheritdoc IRoyalties
    /// @dev Reverts if any node wasn't contributed by msg.sender. Duplicate IDs are harmless:
    ///      the second occurrence finds debt already caught up and pays 0.
    function claim(uint256[] calldata nodeIds) external {
        uint256 total;
        for (uint256 i; i < nodeIds.length; ++i) {
            uint256 id = nodeIds[i];
            if (!graph.nodeExists(id)) revert NotContributor(id);
            (uint256 topicId, address contributor,,,,) = graph.nodes(id);
            if (contributor != msg.sender) revert NotContributor(id);
            uint256 acc = accPerNode[topicId];
            uint256 owed = acc - debt[id];
            if (owed == 0) continue;
            debt[id] = acc;
            total += owed;
            emit Claimed(msg.sender, id, owed);
        }
        if (total > 0) Address.sendValue(payable(msg.sender), total); // state is updated first: no reentrancy gain
    }
}
