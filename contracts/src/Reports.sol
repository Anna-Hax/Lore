// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IReports} from "./interfaces/ILore.sol";
import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";
import {TopicGraph} from "./TopicGraph.sol";
import {Constants} from "./Constants.sol";

/// @notice Leak reports. Anyone can report; the gateway (LEAK_DETECTOR) records the best-matching buyer.
contract Reports is IReports, LoreBase {
    struct Report {
        uint256 topicId;
        address reporter;
        bytes32 evidenceHash;
        uint64 reportedAt;
        address matchedWallet;
        uint16 scoreBps;
        bool matched;
    }

    TopicGraph public immutable graph;
    uint256 public nextReportId = 1;
    mapping(uint256 => Report) private _reports;

    error UnknownTopic(uint256 topicId);
    error UnknownReport(uint256 reportId);
    error AlreadyMatched(uint256 reportId);

    constructor(LoreRoles roles_, TopicGraph graph_) LoreBase(roles_) {
        if (address(graph_) == address(0)) revert ZeroAddress();
        graph = graph_;
    }

    /// @inheritdoc IReports
    function report(uint256 topicId, bytes32 evidenceHash) external returns (uint256 reportId) {
        if (!graph.topicExists(topicId)) revert UnknownTopic(topicId);
        reportId = nextReportId++;
        _reports[reportId] = Report({
            topicId: topicId,
            reporter: msg.sender,
            evidenceHash: evidenceHash,
            reportedAt: uint64(block.timestamp),
            matchedWallet: address(0),
            scoreBps: 0,
            matched: false
        });
        emit LeakReported(reportId, topicId, msg.sender, evidenceHash);
    }

    /// @inheritdoc IReports
    /// @dev Once per report. wallet may be address(0) to record "no match found".
    function recordMatch(uint256 reportId, address wallet, uint16 scoreBps)
        external
        onlyRole(roles.LEAK_DETECTOR_ROLE())
    {
        if (reportId == 0 || reportId >= nextReportId) revert UnknownReport(reportId);
        if (scoreBps > Constants.BPS) revert InvalidParam();
        Report storage r = _reports[reportId];
        if (r.matched) revert AlreadyMatched(reportId);
        r.matched = true;
        r.matchedWallet = wallet;
        r.scoreBps = scoreBps;
        emit LeakMatched(reportId, wallet, scoreBps);
    }

    function getReport(uint256 reportId) external view returns (Report memory) {
        if (reportId == 0 || reportId >= nextReportId) revert UnknownReport(reportId);
        return _reports[reportId];
    }
}
