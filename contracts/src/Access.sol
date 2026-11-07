// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC1155} from "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import {Address} from "@openzeppelin/contracts/utils/Address.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IAccess} from "./interfaces/ILore.sol";
import {IComfyRouter, PoolKey} from "./interfaces/IComfy.sol";
import {LoreBase} from "./LoreBase.sol";
import {LoreRoles} from "./LoreRoles.sol";
import {TopicGraph} from "./TopicGraph.sol";
import {Royalties} from "./Royalties.sol";
import {AuthorTokens} from "./AuthorTokens.sol";
import {LockVault} from "./LockVault.sol";
import {Constants} from "./Constants.sol";

/// @notice Soulbound ERC-1155 access pass, token id = topicId. Buying is the only way to get access.
///         Access is permanent and covers nodes added to the topic later.
///
///         A purchase costs the base price (nodeValue x nodes, paid to the topic's contributors as royalties) plus,
///         for every author, `tokensPerNode` x their nodes of that author's comfy token, bought on comfy in the same
///         transaction at the market price and locked for the buyer in the LockVault. The buyer sends the most they
///         will pay as msg.value (a quote from the gateway plus slippage) and gets the unspent part back.
contract Access is IAccess, ERC1155, LoreBase, ReentrancyGuard {
    TopicGraph public immutable graph;
    Royalties public immutable royalties;
    AuthorTokens public immutable authorTokens;
    LockVault public immutable vault;
    IComfyRouter public immutable router;

    /// @notice Base price per node, in 0G (wei). It goes to the topic's contributors as royalties.
    uint256 public nodeValue = Constants.NODE_VALUE;
    /// @notice Author tokens (18 decimals) a buyer receives per node that author wrote.
    uint256 public tokensPerNode = Constants.TOKENS_PER_NODE;
    /// @notice A topic with more authors than this can't be bought (each author is one comfy swap).
    uint256 public maxAuthors = Constants.MAX_AUTHORS;

    event ParamsSet(uint256 nodeValue, uint256 tokensPerNode, uint256 maxAuthors);
    event AuthorTokensBought(uint256 indexed topicId, address indexed buyer, address indexed token, uint256 amount, uint256 paid);
    event Paid(uint256 indexed topicId, address indexed buyer, uint256 base, uint256 tokens, uint256 refund);

    error Soulbound();
    error Banned(address wallet);
    error AlreadyHeld(uint256 topicId);
    error UnknownTopic(uint256 topicId);
    error TooManyAuthors(uint256 authors, uint256 max);
    error NoAuthorToken(address author);
    error Underpaid(uint256 needed, uint256 sent);
    error UnexpectedNative();

    constructor(
        LoreRoles roles_,
        TopicGraph graph_,
        Royalties royalties_,
        AuthorTokens authorTokens_,
        LockVault vault_,
        IComfyRouter router_
    ) ERC1155("") LoreBase(roles_) {
        if (
            address(graph_) == address(0) || address(royalties_) == address(0) || address(authorTokens_) == address(0)
                || address(vault_) == address(0) || address(router_) == address(0)
        ) revert ZeroAddress();
        graph = graph_;
        royalties = royalties_;
        authorTokens = authorTokens_;
        vault = vault_;
        router = router_;
    }

    function setParams(uint256 nodeValue_, uint256 tokensPerNode_, uint256 maxAuthors_) external onlyAdmin {
        if (maxAuthors_ == 0) revert InvalidParam();
        nodeValue = nodeValue_;
        tokensPerNode = tokensPerNode_;
        maxAuthors = maxAuthors_;
        emit ParamsSet(nodeValue_, tokensPerNode_, maxAuthors_);
    }

    function setURI(string calldata newuri) external onlyAdmin {
        _setURI(newuri);
    }

    /// @inheritdoc IAccess
    /// @dev The base price only. The author-token part depends on comfy's market prices: the gateway quotes it.
    function priceOf(uint256 topicId) public view returns (uint256) {
        return nodeValue * graph.nodeCount(topicId);
    }

    /// @notice What a buyer of `topicId` receives: each author's token and amount.
    function basket(uint256 topicId) external view returns (address[] memory tokens, uint256[] memory amounts) {
        (address[] memory authors, uint256[] memory counts) = graph.topicAuthors(topicId);
        tokens = new address[](authors.length);
        amounts = new uint256[](authors.length);
        for (uint256 i; i < authors.length; ++i) {
            tokens[i] = authorTokens.tokenOf(authors[i]);
            amounts[i] = counts[i] * tokensPerNode;
        }
    }

    /// @inheritdoc IAccess
    function buy(uint256 topicId) external payable nonReentrant {
        if (!graph.topicExists(topicId)) revert UnknownTopic(topicId);
        if (balanceOf(msg.sender, topicId) != 0) revert AlreadyHeld(topicId);
        if (graph.registry().isBanned(msg.sender)) revert Banned(msg.sender);

        uint256 base = priceOf(topicId);
        if (msg.value < base) revert Underpaid(base, msg.value);
        royalties.distribute{value: base}(topicId, base);

        (address[] memory authors, uint256[] memory counts) = graph.topicAuthors(topicId);
        if (authors.length > maxAuthors) revert TooManyAuthors(authors.length, maxAuthors);
        uint256 spent = base;
        for (uint256 i; i < authors.length; ++i) {
            PoolKey memory key = authorTokens.keyOf(authors[i]);
            if (key.currency1 == address(0)) revert NoAuthorToken(authors[i]);
            uint256 amount = counts[i] * tokensPerNode;
            // Offer everything not yet spent; the router takes the market cost and refunds the rest to receive().
            // If the remaining 0G can't cover it, the router reverts and so does the whole purchase.
            uint256 paid = router.buyExactWithNative{value: msg.value - spent}(key, amount, address(vault), block.timestamp);
            spent += paid;
            vault.credit(msg.sender, key.currency1, amount);
            emit AuthorTokensBought(topicId, msg.sender, key.currency1, amount, paid);
        }

        uint256 refund = msg.value - spent;
        // Mint before refunding: the balance is set before any external call that could re-enter (nonReentrant too).
        _mint(msg.sender, topicId, 1, "");
        emit Bought(topicId, msg.sender);
        emit Paid(topicId, msg.sender, base, spent - base, refund);
        if (refund > 0) Address.sendValue(payable(msg.sender), refund);
    }

    /// @inheritdoc IAccess
    function hasAccess(uint256 topicId, address a) external view returns (bool) {
        return balanceOf(a, topicId) != 0 && !graph.registry().isBanned(a);
    }

    /// @dev Only comfy's router refunds unspent 0G here, mid-purchase.
    receive() external payable {
        if (msg.sender != address(router)) revert UnexpectedNative();
    }

    // ---------- soulbound ----------

    /// @dev Minting (from == 0) is the only allowed balance change. Transfers and burns revert.
    function _update(address from, address to, uint256[] memory ids, uint256[] memory values) internal override {
        if (from != address(0)) revert Soulbound();
        super._update(from, to, ids, values);
    }

    function setApprovalForAll(address, bool) public pure override {
        revert Soulbound();
    }
}
