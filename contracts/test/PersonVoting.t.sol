// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Base} from "./Base.t.sol";
import {Submissions} from "../src/Submissions.sol";
import {PersonRegistry} from "../src/PersonRegistry.sol";
import {LoreBase} from "../src/LoreBase.sol";
import {ISubmissions} from "../src/interfaces/ILore.sol";

/// @notice One World ID person = one vote, cast by any one of their agents.
contract PersonVotingTest is Base {
    address bob = makeAddr("bob");

    // ---------- registry ----------

    function test_register_onlyRegistrar() public {
        vm.prank(bob);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        registry.register(bob, _personId(bob));
    }

    function test_register_idempotentButAnAgentNeverChangesPerson() public {
        _link(bob, _personId(bob));
        _link(bob, _personId(bob)); // retry: fine
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(PersonRegistry.AlreadyRegistered.selector, bob));
        registry.register(bob, keccak256("someone else"));
    }

    function test_register_rejectsZeroes() public {
        vm.startPrank(registrar);
        vm.expectRevert(LoreBase.InvalidParam.selector);
        registry.register(address(0), _personId(bob));
        vm.expectRevert(LoreBase.InvalidParam.selector);
        registry.register(bob, bytes32(0));
        vm.stopPrank();
    }

    // ---------- submitting ----------

    function test_submit_requiresAWorldId() public {
        _fund(bob, STAKE);
        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(Submissions.NotRegistered.selector, bob));
        subs.submit(0, _hash(), keccak256("root"));
    }

    // ---------- voting ----------

    function test_onePersonOneVote_anyOfTheirAgentsCanCastIt() public {
        (uint256 topicId, address[] memory c) = _topicWith(3);
        address c1Second = makeAddr("c1 second agent"); // never contributed itself
        _link(c1Second, _personId(c[1]));
        uint256 subId = _submit(alice(), topicId);
        _report(subId, true);

        assertTrue(subs.canVote(subId, c1Second));
        _vote(c1Second, subId, true); // the person votes through their other agent
        assertFalse(subs.canVote(subId, c[1]));
        vm.prank(c[1]);
        vm.expectRevert(Submissions.AlreadyVoted.selector);
        subs.vote(subId, false);
        assertEq(subs.getSubmission(subId).yes, 1);
        assertEq(subs.getSubmission(subId).no, 0);
    }

    function test_quorumCountsPeopleNotAgents() public {
        (uint256 topicId, address[] memory c) = _topicWith(2);
        address c0Second = makeAddr("c0 second agent");
        _link(c0Second, _personId(c[0]));
        _addNode(c0Second, topicId); // same person contributes again through another agent
        assertEq(graph.contributorCount(topicId), 3);
        assertEq(graph.personCount(topicId), 2);

        uint256 subId = _submit(alice(), topicId);
        _report(subId, true);
        assertEq(subs.getSubmission(subId).eligibleVoters, 2);
    }

    function test_submittersOtherAgentsCannotVoteOnIt() public {
        (uint256 topicId, address[] memory c) = _topicWith(2);
        address c0Second = makeAddr("c0 second agent");
        _link(c0Second, _personId(c[0]));
        uint256 subId = _submit(c0Second, topicId); // c[0]'s person submits through another agent
        _report(subId, true);
        assertFalse(subs.canVote(subId, c[0]));
        vm.prank(c[0]);
        vm.expectRevert(Submissions.SubmitterCannotVote.selector);
        subs.vote(subId, true);
    }

    function test_unregisteredAgentCannotVote() public {
        (uint256 topicId,) = _topicWith(2);
        uint256 subId = _submit(alice(), topicId);
        _report(subId, true);
        assertFalse(subs.canVote(subId, bob));
        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(Submissions.NotRegistered.selector, bob));
        subs.vote(subId, true);
    }

    function alice() internal returns (address) {
        return makeAddr("alice-submitter");
    }
}
