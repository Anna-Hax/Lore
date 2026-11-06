// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Base} from "./Base.t.sol";
import {Access} from "../src/Access.sol";
import {Submissions} from "../src/Submissions.sol";
import {LoreBase} from "../src/LoreBase.sol";

/// @notice A proven leaker is removed from Lore completely: every wallet of that person, every topic.
contract BanTest is Base {
    address alice = makeAddr("alice");
    address leaker = makeAddr("leaker");
    address leaker2 = makeAddr("leaker2"); // a second agent of the same person

    function test_onlyLeakDetectorCanBan() public {
        vm.prank(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        registry.ban(leaker);
    }

    function test_banRemovesAccessToEveryTopicForEveryWalletOfThePerson() public {
        (uint256 t1,) = _newTopic(alice);
        (uint256 t2,) = _newTopic(makeAddr("bob"));
        _ensurePerson(leaker);
        _link(leaker2, _personId(leaker));
        _buy(leaker, t1);
        _buy(leaker2, t2);
        assertTrue(access.hasAccess(t1, leaker) && access.hasAccess(t2, leaker2));

        vm.prank(detector);
        registry.ban(leaker);

        assertTrue(registry.isBanned(leaker) && registry.isBanned(leaker2));
        assertFalse(access.hasAccess(t1, leaker));
        assertFalse(access.hasAccess(t2, leaker2)); // the other wallet of the same person
        _fund(leaker2, 100_000000);
        vm.prank(leaker2);
        vm.expectRevert(abi.encodeWithSelector(Access.Banned.selector, leaker2));
        access.buy(t1);
    }

    function test_aWalletLinkedAfterTheBanIsBannedToo() public {
        _ensurePerson(leaker);
        vm.prank(detector);
        registry.ban(leaker);
        address fresh = makeAddr("fresh");
        _link(fresh, _personId(leaker));
        assertTrue(registry.isBanned(fresh));
    }

    function test_bannedPersonCannotSubmitOrVote() public {
        (uint256 t,) = _newTopic(leaker); // the leaker is a contributor, so eligible to vote
        vm.warp(block.timestamp + 1);
        uint256 sub = _submit(alice, t);
        _report(sub, true);
        assertTrue(subs.canVote(sub, leaker));

        vm.prank(detector);
        registry.ban(leaker);

        assertFalse(subs.canVote(sub, leaker));
        vm.prank(leaker);
        vm.expectRevert(abi.encodeWithSelector(Submissions.Banned.selector, leaker));
        subs.vote(sub, true);

        _fund(leaker, 100_000000);
        vm.prank(leaker);
        vm.expectRevert(abi.encodeWithSelector(Submissions.Banned.selector, leaker));
        subs.submit(t, keccak256("leaker-new"), keccak256("root"));
    }

    function test_unlinkedWalletCanBeBannedOnItsOwn() public {
        address anon = makeAddr("anon");
        (uint256 t,) = _newTopic(alice);
        _buy(anon, t);
        vm.prank(detector);
        registry.ban(anon);
        assertFalse(access.hasAccess(t, anon));
        assertFalse(registry.isBanned(alice));
    }
}
