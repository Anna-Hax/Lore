// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {LoreRoles} from "../src/LoreRoles.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {TopicGraph} from "../src/TopicGraph.sol";
import {Submissions} from "../src/Submissions.sol";
import {Access} from "../src/Access.sol";
import {Royalties} from "../src/Royalties.sol";
import {Reports} from "../src/Reports.sol";
import {ISubmissions} from "../src/interfaces/ILore.sol";
import {Constants} from "../src/Constants.sol";

/// @notice Full deployment wired the same way as script/Deploy.s.sol, plus flow helpers.
abstract contract Base is Test {
    LoreRoles roles;
    MockUSDC usdc;
    TopicGraph graph;
    Submissions subs;
    Access access;
    Royalties royalties;
    Reports reports;

    address admin = address(this);
    address treasury = makeAddr("treasury");
    address verifier = makeAddr("verifier");
    address curator = makeAddr("curator");
    address detector = makeAddr("detector");

    uint256 constant STAKE = Constants.STAKE;
    uint256 constant FEE = Constants.STAKE_FEE;
    uint256 constant PRICE = Constants.TOPIC_PRICE;
    uint256 constant WINDOW = Constants.VOTING_WINDOW;

    uint256 private _salt;

    function setUp() public virtual {
        vm.warp(1_700_000_000);
        roles = new LoreRoles(admin, treasury);
        usdc = new MockUSDC();
        graph = new TopicGraph(roles);
        royalties = new Royalties(roles, usdc, graph);
        subs = new Submissions(roles, usdc, graph);
        access = new Access(roles, usdc, graph, royalties);
        reports = new Reports(roles, graph);

        graph.setSubmissions(address(subs));
        graph.setRoyalties(address(royalties));
        royalties.setAccess(address(access));
        roles.grantRole(roles.VERIFIER_ROLE(), verifier);
        roles.grantRole(roles.CURATOR_ROLE(), curator);
        roles.grantRole(roles.LEAK_DETECTOR_ROLE(), detector);
    }

    // ---------- helpers ----------

    function _fund(address who, uint256 amount) internal {
        usdc.mint(who, amount);
        vm.startPrank(who);
        usdc.approve(address(subs), type(uint256).max);
        usdc.approve(address(access), type(uint256).max);
        vm.stopPrank();
    }

    function _hash() internal returns (bytes32) {
        return keccak256(abi.encode("content", ++_salt));
    }

    function _submit(address who, uint256 topicId) internal returns (uint256 subId) {
        if (usdc.balanceOf(who) < STAKE) _fund(who, STAKE * 10);
        vm.prank(who);
        subId = subs.submit(topicId, _hash(), keccak256("root"));
    }

    function _report(uint256 subId, bool pass, uint256[] memory parents) internal {
        vm.prank(verifier);
        subs.postReport(subId, pass, parents, keccak256("report"));
    }

    function _report(uint256 subId, bool pass) internal {
        _report(subId, pass, new uint256[](0));
    }

    function _vote(address who, uint256 subId, bool approve) internal {
        vm.prank(who);
        subs.vote(subId, approve);
    }

    /// @dev New topic accepted by the verifier. Returns (topicId, nodeId).
    function _newTopic(address who) internal returns (uint256 topicId, uint256 nodeId) {
        uint256 subId = _submit(who, 0);
        _report(subId, true);
        subs.finalize(subId);
        nodeId = subs.getSubmission(subId).nodeId;
        (topicId,,,,,) = graph.nodes(nodeId);
    }

    /// @dev Existing-topic node accepted by verifier verdict after the window (no votes). Returns nodeId.
    function _addNode(address who, uint256 topicId, uint256[] memory parents) internal returns (uint256) {
        uint256 subId = _submit(who, topicId);
        _report(subId, true, parents);
        vm.warp(block.timestamp + WINDOW);
        subs.finalize(subId);
        vm.warp(block.timestamp + 1); // so the new contributor predates the next report
        return subs.getSubmission(subId).nodeId;
    }

    function _addNode(address who, uint256 topicId) internal returns (uint256) {
        return _addNode(who, topicId, new uint256[](0));
    }

    /// @dev Topic with `n` distinct contributors c[0..n-1], each with one node.
    function _topicWith(uint256 n) internal returns (uint256 topicId, address[] memory c) {
        c = new address[](n);
        for (uint256 i; i < n; ++i) {
            c[i] = makeAddr(string(abi.encodePacked("contributor", vm.toString(i))));
        }
        (topicId,) = _newTopic(c[0]);
        vm.warp(block.timestamp + 1);
        for (uint256 i = 1; i < n; ++i) {
            _addNode(c[i], topicId);
        }
    }

    function _buy(address who, uint256 topicId) internal {
        if (usdc.balanceOf(who) < access.topicPrice()) _fund(who, access.topicPrice() * 10);
        vm.prank(who);
        access.buy(topicId);
    }

    function _status(uint256 subId) internal view returns (ISubmissions.Status) {
        return subs.getSubmission(subId).status;
    }

    function _arr(uint256 a) internal pure returns (uint256[] memory r) {
        r = new uint256[](1);
        r[0] = a;
    }

    function _arr(uint256 a, uint256 b) internal pure returns (uint256[] memory r) {
        r = new uint256[](2);
        r[0] = a;
        r[1] = b;
    }
}
