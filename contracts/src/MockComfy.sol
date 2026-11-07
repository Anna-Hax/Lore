// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Address} from "@openzeppelin/contracts/utils/Address.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {PoolKey} from "./interfaces/IComfy.sol";

/// @notice Testnet stand-in for comfy (which exists only on 0G mainnet): one contract plays the launcher, the pool
///         manager and the router, with the same function signatures and `Launched` event Lore uses. Prices are set
///         by each token's creator instead of a market. Galileo only; never deploy on mainnet.
contract MockComfy {
    uint256 public constant FEE_BPS = 100; // comfy's base fee on the pools spike C1 read

    struct Pool {
        address token;
        address creator;
        uint256 priceWei; // 0G (wei) per whole token
    }

    mapping(bytes32 => Pool) public pools;
    mapping(address => bool) public isComfyToken;

    event Launched(
        bytes32 indexed poolId, address indexed token, address indexed creator, int24 openingTick, uint256 ladderSupply, uint256 launchFee
    );
    event PriceSet(bytes32 indexed poolId, uint256 priceWei);

    error UnknownPool(bytes32 poolId);
    error NotCreator();
    error Underpaid(uint256 required, uint256 sent);

    function launch(string calldata name, string calldata symbol, uint256 priceWei) external returns (bytes32 poolId, address token) {
        token = address(new MockAgentToken(name, symbol));
        poolId = keccak256(abi.encode(token));
        pools[poolId] = Pool(token, msg.sender, priceWei);
        isComfyToken[token] = true;
        emit Launched(poolId, token, msg.sender, 0, 0, 0);
        emit PriceSet(poolId, priceWei);
    }

    function setPrice(bytes32 poolId, uint256 priceWei) external {
        if (pools[poolId].creator != msg.sender) revert NotCreator();
        pools[poolId].priceWei = priceWei;
        emit PriceSet(poolId, priceWei);
    }

    // ---------- pool manager ----------

    function poolIdToPoolKey(bytes32 id) external view returns (address, address, address, address, uint24, bytes32) {
        address token = pools[id].token;
        return (address(0), token, token == address(0) ? address(0) : address(this), address(this), 0, bytes32(0));
    }

    /// @dev Same encoding as a real pool with native 0G as currency0: sqrtPriceX96 = sqrt(tokens per 0G) * 2^96.
    function getSlot0(bytes32 id) external view returns (uint160 sqrtPriceX96, int24, uint24, uint24) {
        uint256 price = pools[id].priceWei;
        if (price == 0) revert UnknownPool(id);
        sqrtPriceX96 = uint160(Math.sqrt(Math.mulDiv(1e18, 1 << 192, price)));
        return (sqrtPriceX96, 0, 0, 0);
    }

    // ---------- router ----------

    function buyExactWithNative(PoolKey calldata key, uint256 amountOut, address recipient, uint256)
        external
        payable
        returns (uint256 amountIn)
    {
        bytes32 id = keccak256(abi.encode(key.currency1));
        Pool memory p = pools[id];
        if (p.token == address(0)) revert UnknownPool(id);
        uint256 cost = Math.mulDiv(amountOut, p.priceWei, 1e18, Math.Rounding.Ceil);
        amountIn = cost + Math.mulDiv(cost, FEE_BPS, 10_000, Math.Rounding.Ceil);
        if (msg.value < amountIn) revert Underpaid(amountIn, msg.value);
        MockAgentToken(p.token).mint(recipient, amountOut);
        Address.sendValue(payable(p.creator), amountIn); // stands in for the market and the creator's fees
        if (msg.value > amountIn) Address.sendValue(payable(msg.sender), msg.value - amountIn);
    }
}

/// @notice A launch token for MockComfy: plain ERC-20, minted only by the MockComfy that launched it.
contract MockAgentToken is ERC20 {
    address public immutable comfy;

    constructor(string memory name_, string memory symbol_) ERC20(name_, symbol_) {
        comfy = msg.sender;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == comfy, "only MockComfy");
        _mint(to, amount);
    }
}
