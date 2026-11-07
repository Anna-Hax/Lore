// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Test} from "forge-std/Test.sol";
import {LoreRoles} from "../src/LoreRoles.sol";
import {TopicGraph} from "../src/TopicGraph.sol";
import {Submissions} from "../src/Submissions.sol";
import {Access} from "../src/Access.sol";
import {Royalties} from "../src/Royalties.sol";
import {PersonRegistry} from "../src/PersonRegistry.sol";
import {AuthorTokens} from "../src/AuthorTokens.sol";
import {LockVault} from "../src/LockVault.sol";
import {IComfyRouter, IComfyPoolManager} from "../src/interfaces/IComfy.sol";

/// @notice Lore against comfy's real contracts, on a fork of 0G mainnet: nothing is sent to the real chain.
///         Skipped unless COMFY_FORK=1:  COMFY_FORK=1 forge test --match-contract ComfyFork
contract ComfyForkTest is Test {
    // spike/comfy_c1.py: comfy's router (verified source on chainscan) and pool manager, and a live launch pool
    address constant ROUTER = 0x76526f4815447F693468EF44E0204A0689178d9E;
    address constant POOL_MANAGER = 0xAabD31f24914B48dAEA998e69683225E289d08b0;
    bytes32 constant POOL = 0x42b5d7857cd973c19c583863aff4275d92a6bfe04bb3d140e24c2003bb5b2e7c;

    function test_buyingATopicBuysTheAuthorsRealComfyTokens() public {
        if (!vm.envOr("COMFY_FORK", false)) return;
        vm.createSelectFork("https://evmrpc.0g.ai");

        address treasury = makeAddr("treasury");
        LoreRoles roles = new LoreRoles(address(this), treasury);
        TopicGraph graph = new TopicGraph(roles);
        Royalties royalties = new Royalties(roles, graph);
        Submissions subs = new Submissions(roles, graph);
        PersonRegistry registry = new PersonRegistry(roles);
        AuthorTokens authorTokens = new AuthorTokens(roles, IComfyPoolManager(POOL_MANAGER));
        LockVault vault = new LockVault(roles);
        Access access = new Access(roles, graph, royalties, authorTokens, vault, IComfyRouter(ROUTER));
        graph.setSubmissions(address(this)); // stand in for Submissions: add the node directly
        graph.setRoyalties(address(royalties));
        graph.setRegistry(address(registry));
        royalties.setAccess(address(access));
        subs.setAuthorTokens(address(authorTokens));
        vault.setAccess(address(access));
        roles.grantRole(roles.REGISTRAR_ROLE(), address(this));

        address author = makeAddr("author");
        registry.register(author, keccak256("person"));
        authorTokens.link(author, POOL);
        (uint256 topicId,) = graph.addNode(0, author, keccak256("node"), keccak256("root"), new uint256[](0));

        address buyer = makeAddr("buyer");
        vm.deal(buyer, 10 ether);
        vm.prank(buyer);
        access.buy{value: 1 ether}(topicId);

        address token = authorTokens.tokenOf(author);
        assertTrue(access.hasAccess(topicId, buyer));
        assertEq(IERC20(token).balanceOf(address(vault)), access.tokensPerNode(), "real comfy tokens in the vault");
        uint256 spent = 10 ether - buyer.balance;
        emit log_named_decimal_uint("0G spent (base + tokens + comfy charges)", spent, 18);
        assertLt(spent, 1 ether, "the rest was refunded");
        assertEq(address(access).balance, 0, "Access keeps nothing");
    }
}
