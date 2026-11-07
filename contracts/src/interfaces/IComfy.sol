// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice The parts of comfy (0G mainnet) Lore uses, with the same ABI as the deployed contracts. Spike C1
///         (spike/comfy_c1.py) read and simulated them; on Galileo, MockComfy implements the same functions.
/// @dev PoolKey matches PancakeSwap Infinity's (Currency, IHooks and IPoolManager are addresses in the ABI).
///      comfy pools always pair native 0G (currency0 = address(0)) with the launch token (currency1).
struct PoolKey {
    address currency0;
    address currency1;
    address hooks;
    address poolManager;
    uint24 fee;
    bytes32 parameters;
}

interface IComfyRouter {
    /// @notice Buy exactly `amountOut` launch tokens for `recipient`; `msg.value` is the most it may cost and the
    ///         unused part is refunded to the caller (with a full-gas call, so the caller needs a receive()).
    function buyExactWithNative(PoolKey calldata key, uint256 amountOut, address recipient, uint256 deadline)
        external
        payable
        returns (uint256 amountIn);
}

interface IComfyPoolManager {
    function poolIdToPoolKey(bytes32 id)
        external
        view
        returns (address currency0, address currency1, address hooks, address poolManager, uint24 fee, bytes32 parameters);

    function getSlot0(bytes32 id) external view returns (uint160 sqrtPriceX96, int24 tick, uint24 protocolFee, uint24 lpFee);
}
