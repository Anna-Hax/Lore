// Network config. Values for 16602 and 16661 come from the official 0G docs
// (https://docs.0g.ai/ai-context.md, checked 2026-11-06). Don't edit them without re-checking the docs.

/**
 * @typedef {Object} Network
 * @property {string} name
 * @property {number} chainId
 * @property {string} rpcUrl
 * @property {string|null} explorer
 * @property {string|null} faucet
 * @property {string} storageIndexer  0G Storage indexer (turbo) used by @0glabs/0g-ts-sdk
 * @property {string|null} storageFlow  0G Storage flow contract
 */

/** @type {Record<number, Network>} */
export const NETWORKS = {
  // 0G Galileo testnet: the v1 target. The docs mark this public RPC as development-only.
  16602: {
    name: '0G Galileo Testnet',
    chainId: 16602,
    rpcUrl: 'https://evmrpc-testnet.0g.ai',
    explorer: 'https://chainscan-galileo.0g.ai',
    faucet: 'https://faucet.0g.ai',
    storageIndexer: 'https://indexer-storage-testnet-turbo.0g.ai',
    storageFlow: '0x22E03a6A89B950F1c82ec5e74F8eCa321a105296',
  },
  // 0G Aristotle mainnet: reference only, not used in v1.
  16661: {
    name: '0G Mainnet',
    chainId: 16661,
    rpcUrl: 'https://evmrpc.0g.ai',
    explorer: 'https://chainscan.0g.ai',
    faucet: null,
    storageIndexer: 'https://indexer-storage-turbo.0g.ai',
    storageFlow: '0x62D4144dB0F0a6fBBaeb6296c785C71B3D57C526',
  },
  // Local anvil for development before M1. Contracts run locally, but storage still goes to the
  // 0G testnet indexer, because there is no local 0G Storage. Uploads need a testnet-funded key.
  31337: {
    name: 'Anvil (local)',
    chainId: 31337,
    rpcUrl: 'http://127.0.0.1:8545',
    explorer: null,
    faucet: null,
    storageIndexer: 'https://indexer-storage-testnet-turbo.0g.ai',
    storageFlow: '0x22E03a6A89B950F1c82ec5e74F8eCa321a105296',
  },
};

/** The chain v1 targets. */
export const DEFAULT_CHAIN_ID = 16602;

/**
 * @param {number} [chainId]
 * @returns {Network}
 */
export function getNetwork(chainId = DEFAULT_CHAIN_ID) {
  const n = NETWORKS[chainId];
  if (!n) throw new Error(`Unknown chainId ${chainId}`);
  return n;
}
