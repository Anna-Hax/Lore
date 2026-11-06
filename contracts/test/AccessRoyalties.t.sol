// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Base} from "./Base.t.sol";
import {Access} from "../src/Access.sol";
import {Royalties} from "../src/Royalties.sol";
import {Reports} from "../src/Reports.sol";
import {LoreBase} from "../src/LoreBase.sol";
import {IAccess, IReports} from "../src/interfaces/ILore.sol";

contract AccessTest is Base {
    address alice = makeAddr("alice");
    address buyer = makeAddr("buyer");

    function test_buy_mintsAndGrantsAccess() public {
        (uint256 t,) = _newTopic(alice);
        assertFalse(access.hasAccess(t, buyer));
        _fund(buyer, PRICE);
        vm.expectEmit(address(access));
        emit IAccess.Bought(t, buyer);
        vm.prank(buyer);
        access.buy(t);
        assertTrue(access.hasAccess(t, buyer));
        assertEq(access.balanceOf(buyer, t), 1);
        assertEq(usdc.balanceOf(buyer), 0);
    }

    function test_buy_secondBuyReverts() public {
        (uint256 t,) = _newTopic(alice);
        _buy(buyer, t);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Access.AlreadyHeld.selector, t));
        access.buy(t);
    }

    function test_buy_unknownTopicReverts() public {
        _fund(buyer, PRICE);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Access.UnknownTopic.selector, 1));
        access.buy(1);
    }

    function test_contributingDoesNotGrantAccess() public {
        (uint256 t,) = _newTopic(alice);
        assertFalse(access.hasAccess(t, alice));
    }

    function test_soulbound_transfersRevert() public {
        (uint256 t,) = _newTopic(alice);
        _buy(buyer, t);
        vm.startPrank(buyer);
        vm.expectRevert(Access.Soulbound.selector);
        access.safeTransferFrom(buyer, alice, t, 1, "");
        uint256[] memory ids = new uint256[](1);
        uint256[] memory vals = new uint256[](1);
        ids[0] = t;
        vals[0] = 1;
        vm.expectRevert(Access.Soulbound.selector);
        access.safeBatchTransferFrom(buyer, alice, ids, vals, "");
        vm.expectRevert(Access.Soulbound.selector);
        access.setApprovalForAll(alice, true);
        vm.stopPrank();
        assertTrue(access.hasAccess(t, buyer));
    }

    function test_accessCoversLaterNodes() public {
        (uint256 t,) = _newTopic(alice);
        _buy(buyer, t);
        _addNode(makeAddr("bob"), t);
        assertTrue(access.hasAccess(t, buyer)); // access is per topic, not per node
    }

    function test_setTopicPrice_onlyAdmin() public {
        vm.prank(buyer);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        access.setTopicPrice(1);
    }
}

contract RoyaltiesTest is Base {
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");

    function test_distribute_onlyAccess() public {
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        royalties.distribute(1, 1);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        royalties.onNodeAdded(1, 1);
    }

    function test_sale_splitsCutAndNodes() public {
        (uint256 t, uint256 n1) = _newTopic(alice);
        uint256 tBefore = usdc.balanceOf(treasury);
        _buy(makeAddr("b1"), t);
        assertEq(usdc.balanceOf(treasury) - tBefore, PRICE / 10); // 10% cut, no dust
        assertEq(royalties.claimable(n1), PRICE * 9 / 10);
    }

    function test_nodeAcceptedAfterSale_earnsNothingFromIt() public {
        (uint256 t, uint256 n1) = _newTopic(alice);
        _buy(makeAddr("b1"), t); // n1 gets 4.5
        uint256 n2 = _addNode(bob, t);
        assertEq(royalties.claimable(n2), 0);
        _buy(makeAddr("b2"), t); // 4.5 / 2 each
        assertEq(royalties.claimable(n1), 4_500000 + 2_250000);
        assertEq(royalties.claimable(n2), 2_250000);
    }

    function test_dustToTreasury() public {
        access.setTopicPrice(5_000001);
        (uint256 t, uint256 n1) = _newTopic(alice);
        uint256 n2 = _addNode(bob, t);
        uint256 tBefore = usdc.balanceOf(treasury);
        _buy(makeAddr("b1"), t);
        // cut = floor(5_000001 * 0.1) = 500000; rest 4_500001; per node 2_250000; dust 1
        assertEq(usdc.balanceOf(treasury) - tBefore, 500001);
        assertEq(royalties.claimable(n1), 2_250000);
        assertEq(royalties.claimable(n2), 2_250000);
        assertEq(usdc.balanceOf(address(royalties)), 4_500000);
    }

    function test_claim_paysContributorOnce() public {
        (uint256 t, uint256 n1) = _newTopic(alice);
        _buy(makeAddr("b1"), t);
        uint256 before = usdc.balanceOf(alice);
        vm.prank(alice);
        royalties.claim(_arr(n1, n1)); // duplicate id pays once
        assertEq(usdc.balanceOf(alice) - before, 4_500000);
        assertEq(royalties.claimable(n1), 0);
        vm.prank(alice);
        royalties.claim(_arr(n1)); // nothing left, no revert
        assertEq(usdc.balanceOf(alice) - before, 4_500000);
    }

    function test_claim_notContributorReverts() public {
        (uint256 t, uint256 n1) = _newTopic(alice);
        _buy(makeAddr("b1"), t);
        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(Royalties.NotContributor.selector, n1));
        royalties.claim(_arr(n1));
        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(Royalties.NotContributor.selector, 42));
        royalties.claim(_arr(42));
    }

    function test_claimableMany() public {
        (uint256 t, uint256 n1) = _newTopic(alice);
        uint256 n2 = _addNode(alice, t);
        _buy(makeAddr("b1"), t);
        assertEq(royalties.claimableMany(_arr(n1, n2)), 4_500000);
    }

    function test_setPlatformCut_guard() public {
        vm.expectRevert(LoreBase.InvalidParam.selector);
        royalties.setPlatformCutBps(10_001);
    }
}

contract ReportsTest is Base {
    address alice = makeAddr("alice");

    function test_reportAndMatch() public {
        (uint256 t,) = _newTopic(alice);
        vm.expectEmit(address(reports));
        emit IReports.LeakReported(1, t, alice, keccak256("ev"));
        vm.prank(alice);
        uint256 id = reports.report(t, keccak256("ev"));
        assertEq(id, 1);

        vm.prank(alice);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        reports.recordMatch(id, alice, 9000);

        vm.prank(detector);
        reports.recordMatch(id, makeAddr("leaker"), 9000);
        Reports.Report memory r = reports.getReport(id);
        assertEq(r.matchedWallet, makeAddr("leaker"));
        assertEq(r.scoreBps, 9000);

        vm.prank(detector);
        vm.expectRevert(abi.encodeWithSelector(Reports.AlreadyMatched.selector, id));
        reports.recordMatch(id, alice, 1);
    }

    function test_report_unknownTopicReverts() public {
        vm.expectRevert(abi.encodeWithSelector(Reports.UnknownTopic.selector, 3));
        reports.report(3, bytes32(0));
    }

    function test_recordMatch_guards() public {
        (uint256 t,) = _newTopic(alice);
        uint256 id = reports.report(t, bytes32(0));
        vm.startPrank(detector);
        vm.expectRevert(abi.encodeWithSelector(Reports.UnknownReport.selector, 2));
        reports.recordMatch(2, alice, 1);
        vm.expectRevert(LoreBase.InvalidParam.selector);
        reports.recordMatch(id, alice, 10_001);
        vm.stopPrank();
    }
}
