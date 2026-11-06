// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Base} from "./Base.t.sol";
import {TopicGraph} from "../src/TopicGraph.sol";
import {LoreBase} from "../src/LoreBase.sol";
import {ITopicGraph} from "../src/interfaces/ILore.sol";

/// @dev Calls addNode directly by pranking as Submissions, so parent rules are tested at the graph itself.
contract TopicGraphTest is Base {
    address alice = makeAddr("alice");

    function setUp() public override {
        super.setUp();
        _ensurePerson(alice); // every contributor has a World ID
    }

    function _add(uint256 topicId, uint256[] memory parents) internal returns (uint256 t, uint256 n) {
        vm.prank(address(subs));
        (t, n) = graph.addNode(topicId, alice, _hash(), bytes32(0), parents);
    }

    function test_addNode_onlySubmissions() public {
        vm.prank(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        graph.addNode(0, alice, bytes32(0), bytes32(0), new uint256[](0));
    }

    function test_addNode_createsTopicAndIds() public {
        vm.expectEmit(address(graph));
        emit ITopicGraph.TopicCreated(1);
        (uint256 t1, uint256 n1) = _add(0, new uint256[](0));
        (uint256 t2, uint256 n2) = _add(0, new uint256[](0));
        (uint256 t3, uint256 n3) = _add(t1, _arr(n1));
        assertEq(t1, 1);
        assertEq(t2, 2);
        assertEq(t3, 1);
        assertEq(n1, 1);
        assertEq(n2, 2);
        assertEq(n3, 3);
        assertEq(graph.nodeCount(1), 2);
        assertEq(graph.contributorCount(1), 1); // same contributor counted once
        assertEq(graph.topicNodes(1), _arr(1, 3));
    }

    function test_addNode_unknownTopicReverts() public {
        vm.prank(address(subs));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.UnknownTopic.selector, 5));
        graph.addNode(5, alice, bytes32(0), bytes32(0), new uint256[](0));
    }

    function test_parents_wrongTopic() public {
        (, uint256 nA) = _add(0, new uint256[](0));
        (uint256 tB,) = _add(0, new uint256[](0));
        vm.prank(address(subs));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.ParentNotInTopic.selector, nA));
        graph.addNode(tB, alice, bytes32(0), bytes32(0), _arr(nA));
    }

    function test_parents_missing() public {
        (uint256 t,) = _add(0, new uint256[](0));
        vm.prank(address(subs));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.ParentNotInTopic.selector, 99));
        graph.addNode(t, alice, bytes32(0), bytes32(0), _arr(99));
        vm.prank(address(subs));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.ParentNotInTopic.selector, 0));
        graph.addNode(t, alice, bytes32(0), bytes32(0), _arr(0));
    }

    function test_parents_duplicate() public {
        (uint256 t, uint256 n) = _add(0, new uint256[](0));
        vm.prank(address(subs));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.DuplicateParent.selector, n));
        graph.addNode(t, alice, bytes32(0), bytes32(0), _arr(n, n));
    }

    function test_parents_tooMany() public {
        (uint256 t,) = _add(0, new uint256[](0));
        for (uint256 i; i < 5; ++i) {
            _add(t, new uint256[](0));
        }
        uint256[] memory six = new uint256[](6);
        for (uint256 i; i < 6; ++i) {
            six[i] = i + 1;
        }
        vm.prank(address(subs));
        vm.expectRevert(TopicGraph.TooManyParents.selector);
        graph.addNode(t, alice, bytes32(0), bytes32(0), six);

        uint256[] memory five = new uint256[](5);
        for (uint256 i; i < 5; ++i) {
            five[i] = i + 1;
        }
        (, uint256 n) = _add(t, five); // exactly MAX_PARENTS is fine
        assertEq(graph.parentsOf(n).length, 5);
    }

    function test_parents_newTopicCannotHaveParents() public {
        (, uint256 n) = _add(0, new uint256[](0));
        vm.prank(address(subs));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.ParentNotInTopic.selector, n));
        graph.addNode(0, alice, bytes32(0), bytes32(0), _arr(n));
    }

    function test_meta_onlyCurator() public {
        (uint256 t, uint256 n) = _add(0, new uint256[](0));
        vm.prank(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        graph.setNodeMeta(n, keccak256("m"));
        vm.prank(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        graph.setTopicMeta(t, keccak256("m"));

        vm.startPrank(curator);
        vm.expectEmit(address(graph));
        emit ITopicGraph.NodeMetaSet(n, keccak256("node"));
        graph.setNodeMeta(n, keccak256("node"));
        graph.setTopicMeta(t, keccak256("topic"));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.UnknownNode.selector, 9));
        graph.setNodeMeta(9, bytes32(0));
        vm.expectRevert(abi.encodeWithSelector(TopicGraph.UnknownTopic.selector, 9));
        graph.setTopicMeta(9, bytes32(0));
        vm.stopPrank();

        assertEq(graph.getNode(n).metaHash, keccak256("node"));
        assertEq(graph.topicMeta(t), keccak256("topic"));
    }

    function test_wiring_onlyAdmin() public {
        vm.startPrank(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        graph.setSubmissions(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        graph.setRoyalties(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        graph.setMaxParents(1);
        vm.stopPrank();
    }
}
