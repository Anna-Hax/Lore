// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ITopicGraph} from "./interfaces/ILore.sol";
import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";
import {Constants} from "./Constants.sol";
import {PersonRegistry} from "./PersonRegistry.sol";

interface IRoyaltiesNodeHook {
    function onNodeAdded(uint256 topicId, uint256 nodeId) external;
}

/// @notice Every topic is a DAG of accepted nodes. Node and topic IDs are global, start at 1 and only grow,
///         so a parent always has a smaller ID than its child and the graph can't contain a cycle.
contract TopicGraph is ITopicGraph, LoreBase {
    /// @notice The only address allowed to call addNode.
    address public submissions;
    /// @notice Notified on every new node so it can snapshot the royalty accumulator.
    address public royalties;
    /// @notice agent -> person (World ID). Every contributor must be registered.
    PersonRegistry public registry;
    uint256 public maxParents = Constants.MAX_PARENTS;

    uint256 public nextTopicId = 1;
    uint256 public nextNodeId = 1;

    /// @notice nodeId => node. nodeId 0 never exists.
    mapping(uint256 => Node) public nodes;
    /// @notice topicId => keccak256 of the curator's canonical TopicMeta JSON.
    mapping(uint256 => bytes32) public topicMeta;

    mapping(uint256 => uint256[]) private _parents;
    mapping(uint256 => uint256[]) private _topicNodes;
    mapping(uint256 => mapping(address => uint64)) private _contributorSince;
    mapping(uint256 => uint256) private _contributorCount;
    mapping(uint256 => mapping(bytes32 => uint64)) private _personSince;
    mapping(uint256 => uint256) private _personCount;

    event SubmissionsSet(address submissions);
    event RoyaltiesSet(address royalties);
    event RegistrySet(address registry);
    event MaxParentsSet(uint256 maxParents);

    error UnknownTopic(uint256 topicId);
    error UnknownNode(uint256 nodeId);
    error TooManyParents();
    error ParentNotInTopic(uint256 parentId);
    error DuplicateParent(uint256 parentId);
    error NotWired();
    error NotRegistered(address agent);

    constructor(LoreRoles roles_) LoreBase(roles_) {}

    // ---------- wiring / admin ----------

    function setSubmissions(address s) external onlyAdmin {
        if (s == address(0)) revert ZeroAddress();
        submissions = s;
        emit SubmissionsSet(s);
    }

    function setRoyalties(address r) external onlyAdmin {
        if (r == address(0)) revert ZeroAddress();
        royalties = r;
        emit RoyaltiesSet(r);
    }

    function setRegistry(address r) external onlyAdmin {
        if (r == address(0)) revert ZeroAddress();
        registry = PersonRegistry(r);
        emit RegistrySet(r);
    }

    function setMaxParents(uint256 m) external onlyAdmin {
        if (m == 0) revert InvalidParam();
        maxParents = m;
        emit MaxParentsSet(m);
    }

    // ---------- writes ----------

    /// @inheritdoc ITopicGraph
    function addNode(
        uint256 topicId,
        address contributor,
        bytes32 contentHash,
        bytes32 storageRoot,
        uint256[] calldata parents
    ) external returns (uint256 topicIdOut, uint256 nodeId) {
        if (msg.sender != submissions) revert NotAuthorized();
        if (royalties == address(0) || address(registry) == address(0)) revert NotWired();
        if (contributor == address(0)) revert ZeroAddress();
        bytes32 person = registry.personOf(contributor);
        if (person == bytes32(0)) revert NotRegistered(contributor);

        if (topicId == 0) {
            topicIdOut = nextTopicId++;
            emit TopicCreated(topicIdOut);
        } else {
            if (!topicExists(topicId)) revert UnknownTopic(topicId);
            topicIdOut = topicId;
        }
        // A brand-new topic has no nodes, so any parent fails the same-topic check.
        checkParents(topicIdOut, parents);

        nodeId = nextNodeId++;
        nodes[nodeId] = Node({
            topicId: topicIdOut,
            contributor: contributor,
            contentHash: contentHash,
            storageRoot: storageRoot,
            metaHash: bytes32(0),
            acceptedAt: uint64(block.timestamp)
        });
        _parents[nodeId] = parents;
        _topicNodes[topicIdOut].push(nodeId);

        if (_contributorSince[topicIdOut][contributor] == 0) {
            _contributorSince[topicIdOut][contributor] = uint64(block.timestamp);
            _contributorCount[topicIdOut]++;
        }
        if (_personSince[topicIdOut][person] == 0) {
            _personSince[topicIdOut][person] = uint64(block.timestamp);
            _personCount[topicIdOut]++;
        }

        IRoyaltiesNodeHook(royalties).onNodeAdded(topicIdOut, nodeId);
        emit NodeAdded(topicIdOut, nodeId, contributor, parents);
    }

    /// @inheritdoc ITopicGraph
    function setNodeMeta(uint256 nodeId, bytes32 metaHash) external onlyRole(roles.CURATOR_ROLE()) {
        if (!nodeExists(nodeId)) revert UnknownNode(nodeId);
        nodes[nodeId].metaHash = metaHash;
        emit NodeMetaSet(nodeId, metaHash);
    }

    /// @inheritdoc ITopicGraph
    function setTopicMeta(uint256 topicId, bytes32 metaHash) external onlyRole(roles.CURATOR_ROLE()) {
        if (!topicExists(topicId)) revert UnknownTopic(topicId);
        topicMeta[topicId] = metaHash;
        emit TopicMetaSet(topicId, metaHash);
    }

    // ---------- views ----------

    /// @notice Reverts unless `parents` is a valid parent list for a new node in `topicId`:
    ///         every parent exists in that topic, no duplicates, at most `maxParents`.
    /// @dev Submissions also calls this in postReport, so a report can never make finalize revert later.
    function checkParents(uint256 topicId, uint256[] calldata parents) public view {
        uint256 n = parents.length;
        if (n > maxParents) revert TooManyParents();
        for (uint256 i; i < n; ++i) {
            uint256 p = parents[i];
            if (p == 0 || p >= nextNodeId || nodes[p].topicId != topicId) revert ParentNotInTopic(p);
            for (uint256 j; j < i; ++j) {
                if (parents[j] == p) revert DuplicateParent(p);
            }
        }
    }

    function topicExists(uint256 topicId) public view returns (bool) {
        return topicId != 0 && topicId < nextTopicId;
    }

    function nodeExists(uint256 nodeId) public view returns (bool) {
        return nodeId != 0 && nodeId < nextNodeId;
    }

    function topicCount() external view returns (uint256) {
        return nextTopicId - 1;
    }

    function getNode(uint256 nodeId) external view returns (Node memory) {
        if (!nodeExists(nodeId)) revert UnknownNode(nodeId);
        return nodes[nodeId];
    }

    function topicNodes(uint256 topicId) external view returns (uint256[] memory) {
        return _topicNodes[topicId];
    }

    /// @inheritdoc ITopicGraph
    function nodeCount(uint256 topicId) external view returns (uint256) {
        return _topicNodes[topicId].length;
    }

    /// @inheritdoc ITopicGraph
    function contributorSince(uint256 topicId, address a) external view returns (uint64) {
        return _contributorSince[topicId][a];
    }

    /// @inheritdoc ITopicGraph
    function contributorCount(uint256 topicId) external view returns (uint256) {
        return _contributorCount[topicId];
    }

    /// @inheritdoc ITopicGraph
    function personSince(uint256 topicId, bytes32 person) external view returns (uint64) {
        return _personSince[topicId][person];
    }

    /// @inheritdoc ITopicGraph
    function personCount(uint256 topicId) external view returns (uint256) {
        return _personCount[topicId];
    }

    /// @inheritdoc ITopicGraph
    function parentsOf(uint256 nodeId) external view returns (uint256[] memory) {
        return _parents[nodeId];
    }
}
