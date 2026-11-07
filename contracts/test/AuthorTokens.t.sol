// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Base} from "./Base.t.sol";
import {Access} from "../src/Access.sol";
import {AuthorTokens} from "../src/AuthorTokens.sol";
import {LockVault} from "../src/LockVault.sol";
import {MockComfy} from "../src/MockComfy.sol";
import {Submissions} from "../src/Submissions.sol";
import {LoreBase} from "../src/LoreBase.sol";
import {Constants} from "../src/Constants.sol";

/// @notice Authors need a comfy token; buying a topic buys its authors' tokens into the lock vault.
contract AuthorTokensTest is Base {
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address buyer = makeAddr("buyer");
    uint256 constant TPN = Constants.TOKENS_PER_NODE;

    function test_submitWithoutAnAuthorTokenReverts() public {
        _ensurePerson(alice);
        _fund(alice, STAKE);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(Submissions.NoAuthorToken.selector, alice));
        subs.submit{value: STAKE}(0, keccak256("x"), keccak256("root"));
    }

    function test_submitNeedsTheExactStake() public {
        _ensurePerson(alice);
        _ensureToken(alice);
        _fund(alice, STAKE);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(Submissions.WrongStake.selector, STAKE, STAKE - 1));
        subs.submit{value: STAKE - 1}(0, keccak256("x"), keccak256("root"));
    }

    function test_link_onlyRegistrar_andOnlyRealPools() public {
        vm.prank(alice);
        (bytes32 poolId, address token) = comfy.launch("A", "A", TOKEN_PRICE);
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        authorTokens.link(alice, poolId);
        vm.prank(registrar);
        vm.expectRevert(abi.encodeWithSelector(AuthorTokens.NotAComfyPool.selector, bytes32(uint256(1))));
        authorTokens.link(alice, bytes32(uint256(1)));
        vm.prank(registrar);
        authorTokens.link(alice, poolId);
        assertEq(authorTokens.tokenOf(alice), token);
    }

    /// @dev Alice wrote 2 nodes and Bob 1: the buyer pays base + 2*TPN of Alice's token + TPN of Bob's.
    function _twoAuthorTopic() internal returns (uint256 t) {
        (t,) = _newTopic(alice);
        vm.warp(block.timestamp + 1);
        _addNode(alice, t);
        _addNode(bob, t);
    }

    function test_buy_buysEachAuthorsTokensIntoTheVault_andRefunds() public {
        uint256 t = _twoAuthorTopic();
        uint256 cost = _cost(t);
        uint256 royaltiesBefore = _bal(address(royalties));
        _fund(buyer, cost + 1 ether);
        vm.prank(buyer);
        access.buy{value: cost + 1 ether}(t);

        assertEq(_bal(buyer), 1 ether, "unspent 0G is refunded");
        assertTrue(access.hasAccess(t, buyer));
        assertEq(_bal(address(royalties)) - royaltiesBefore, 3 * PRICE - 3 * PRICE / 10, "base to royalties minus cut");
        (address[] memory tokens, uint256[] memory amounts) = access.basket(t);
        assertEq(tokens[0], authorTokens.tokenOf(alice));
        assertEq(amounts[0], 2 * TPN);
        assertEq(amounts[1], TPN);
        for (uint256 i; i < 2; ++i) {
            assertEq(IERC20(tokens[i]).balanceOf(address(vault)), amounts[i]);
            (uint256 locked, uint64 unlockAt) = vault.locks(buyer, tokens[i]);
            assertEq(locked, amounts[i]);
            assertEq(unlockAt, block.timestamp + Constants.LOCK_PERIOD);
        }
        assertEq(_bal(address(access)), 0, "Access keeps nothing");
    }

    function test_buy_underpaidRevertsAndChangesNothing() public {
        uint256 t = _twoAuthorTopic();
        uint256 cost = _cost(t);
        _fund(buyer, cost);
        vm.prank(buyer);
        vm.expectRevert(); // the router can't cover the last author's tokens
        access.buy{value: cost - 1}(t);
        assertFalse(access.hasAccess(t, buyer));
        assertEq(_bal(buyer), cost);
    }

    function test_buy_belowTheBasePriceReverts() public {
        (uint256 t,) = _newTopic(alice);
        _fund(buyer, PRICE);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Access.Underpaid.selector, PRICE, PRICE - 1));
        access.buy{value: PRICE - 1}(t);
    }

    function test_buy_tooManyAuthorsReverts() public {
        uint256 t = _twoAuthorTopic();
        access.setParams(PRICE, TPN, 1);
        uint256 cost = _cost(t);
        _fund(buyer, cost);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Access.TooManyAuthors.selector, 2, 1));
        access.buy{value: cost}(t);
    }

    function test_vault_claimOnlyAfterTheLock() public {
        uint256 t = _twoAuthorTopic();
        _buy(buyer, t);
        address token = authorTokens.tokenOf(bob);
        (, uint64 unlockAt) = vault.locks(buyer, token);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(LockVault.Locked.selector, unlockAt));
        vault.claim(token);

        vm.warp(unlockAt);
        vm.prank(buyer);
        vault.claim(token);
        assertEq(IERC20(token).balanceOf(buyer), TPN);
        vm.prank(buyer);
        vm.expectRevert(LockVault.NothingToClaim.selector);
        vault.claim(token);
    }

    function test_vault_creditOnlyFromAccess() public {
        vm.expectRevert(LoreBase.NotAuthorized.selector);
        vault.credit(buyer, address(1), 1);
    }

    function test_access_acceptsNativeOnlyFromTheRouter() public {
        vm.deal(address(this), 1);
        (bool ok,) = address(access).call{value: 1}("");
        assertFalse(ok);
    }

    function test_mockComfy_priceMatchesTheRealPoolEncoding() public {
        vm.prank(alice);
        (bytes32 poolId,) = comfy.launch("A", "A", TOKEN_PRICE);
        (uint160 sqrtPriceX96,,,) = comfy.getSlot0(poolId);
        // 0G per token = 2^192 / sqrtPriceX96^2, the formula the gateway uses on comfy's pools
        uint256 back = (uint256(1) << 192) / (uint256(sqrtPriceX96) * sqrtPriceX96 / 1e18);
        assertApproxEqRel(back, TOKEN_PRICE, 1e12); // within 0.0001%
    }
}
