# Lore contracts (P2)

Foundry project for Workstream A of `BUILD_PLAN.md`. Frozen interfaces are in `src/interfaces/ILore.sol`.

| Contract | Does |
|---|---|
| `LoreRoles` | OZ AccessControl: `ADMIN_ROLE`, `VERIFIER_ROLE`, `CURATOR_ROLE`, `LEAK_DETECTOR_ROLE`, plus the `treasury` address |
| `TopicGraph` | Topics as DAGs of accepted nodes; node/topic metadata hashes |
| `Submissions` | Stake → verifier report → contributor vote → finalize; slash split and `claimSlash` |
| `Access` | Soulbound ERC-1155 access pass, id = topicId |
| `Royalties` | Per-sale split with an accumulator; `claim` |
| `Reports` | Leak reports and `recordMatch` |
| `MockUSDC` | Testnet USDC, 6 decimals, open `mint` |

## Setup

```bash
git submodule update --init --recursive
forge build
forge test
```

## Deploy locally (anvil)

```bash
anvil
forge script script/Deploy.s.sol --rpc-url anvil --broadcast
node script/export-abi.mjs
```

On anvil every role defaults to account #0. Output: `packages/shared/src/deployments/31337.json` and `packages/shared/src/abi/*.json`.

## Deploy to 0G Galileo testnet (chain 16602)

Get testnet 0G for the deployer from https://faucet.0g.ai, then:

```bash
export DEPLOYER_PRIVATE_KEY=0x...      # never commit
export TREASURY=0x...                  # optional, default deployer
export VERIFIER=0x...                  # verifier agent wallet
export CURATOR=0x...                   # curator agent wallet
export LEAK_DETECTOR=0x...             # gateway agent wallet (it calls recordMatch)
forge script script/Deploy.s.sol --rpc-url og_testnet --broadcast
node script/export-abi.mjs
```

If the RPC rejects EIP-1559 transactions, add `--legacy`. Commit `deployments/16602.json` afterwards.

Role wallets can also be granted later by the admin:

```bash
cast send <LoreRoles> "grantRole(bytes32,address)" $(cast keccak VERIFIER) <wallet> --rpc-url og_testnet --private-key $DEPLOYER_PRIVATE_KEY
```

## Notes for P1 and P3

- **IDs:** topic, node, submission and report IDs all start at 1. `0` means "none" (e.g. `nodeId` in a rejected `Finalized`, or `topicId` 0 in `submit` = new topic).
- **Gateway checks:** `Submissions.canVote(subId, addr)` and `canFinalize(subId)` mirror the contract rules exactly. Use them instead of re-implementing the rules. `Access.hasAccess` for reads; `LoreRoles.isVerifier` / `isCurator` for the `lore_internal_*` tools.
- **Extra views** beyond section 3.2 (additive only): `TopicGraph.getNode`, `nodes`, `topicNodes`, `topicMeta`, `topicExists`, `nodeExists`, `topicCount`, `checkParents`; `Submissions.getSubmission`, `voteOf`, `quorumThreshold`, `votingEndsAt`, `submissionCount`, `claimSlash`; `Royalties.claimableMany`; `Reports.getReport`.
- **Quorum:** reached when at least `quorumBps` of the eligible voters voted. Early finalize when one side alone is *above* `eligibleVoters × quorumBps / 1e4`. `quorumBps` can't be set below 50%, which is what makes early finalize safe.
- **Parents** are validated in `postReport`, so a bad report reverts there instead of making `finalize` fail later. A new-topic report must have no parents.
- **Config:** every value in section 3.1 is stored on-chain and settable by ADMIN (`Submissions.setParams`, `Access.setTopicPrice`, `Royalties.setPlatformCutBps`, `TopicGraph.setMaxParents`). Stake and fee are snapshotted per submission.
- A submission the verifier never reports stays `Pending` with its stake locked. There is no timeout in v1.
