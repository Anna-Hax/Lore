# Lore v1 — Build Plan

Audience: the coding agents (and their humans) building Lore v1. Read this whole file before starting your workstream. Product spec: https://claude.ai/artifact/KvzhXcdgHuhuBvokj7iKbf

**Goal of v1:** the full marketplace loop running end to end on the 0G testnet. An agent submits research, it gets verified and voted on, it becomes a node in a topic graph, another agent buys the topic and reads a watermarked copy, and contributors claim royalties.

---

## 0. Team split (3 people)

| Person | Role | Owns | Paths |
|---|---|---|---|
| **P1** | Agent developer | B (gateway: MCP server, queue, indexer, finalizer, `lore-skill`) and D (verifier and curator agents) | `agents/*`, `packages/lore-skill/` |
| **P2** | Blockchain developer | A (all contracts, tests, deploy script, ABI export, testnet deploys, network config) | `contracts/`, `packages/shared/src/{abi,deployments,network.js}` |
| **P3** | Platform and integration | S (Launchpad spike), C libraries (crypto, watermark, leak scoring), `packages/shared` scaffold and types, Launchpad deployment of all agents, E (end-to-end) | `spike/`, `packages/shared/src/{crypto,watermark,leak,types,constants,canonical}.js`, `e2e/` |

Handoffs:
- **P2 → P1, P3:** ABIs and deployment addresses in `packages/shared`. Use the local anvil deploy until testnet is ready.
- **P3 → P1:** two pure, tested libraries. The first is `crypto.js` and `watermark.js`. The second is `leak.js`, which provides `bestMatch(text, candidates) → {wallet, scoreBps}`. P1 wires them into the gateway's MCP tools; P3 never edits `agents/*`.
- **P3 → everyone:** spike findings. They decide how P1 packages the agents and where their state lives.
- **Section 3 (frozen interfaces):** a change needs approval from all three.

---

## 1. Product rules (the parts you need to code against)

- **Topic:** one commit graph, which is a DAG of nodes. A node can have 0..n parents, and a topic can have several top-level nodes.
- **Node:** encrypted text plus public metadata (title and description). Only Lore's curator agent writes metadata; the submitter never does.
- **Access:** only `buy(topicId)` grants access. The price is fixed and paid in USDC. The token is a soulbound ERC-1155 (non-transferable), one token ID per topic. Access is permanent and includes nodes added later. Contributing never grants access.
- **Voting:**
  - Only agents with an accepted node in the topic can vote on its submissions.
  - A voter sees three things: the submission text, the verifier report, and the public metadata of the suggested parents. Nothing else.
  - The voting window is 24h. If quorum isn't reached, the verifier's verdict stands.
  - On a **new topic**, the verifier is the only voter.
- **Hosting:** every agent, Lore's and every user's, runs on the [0G Agent Launchpad](https://app.0g.ai/agent-launchpad). Lore runs no server of its own.
- **Queue:** every agent request goes through the MCP endpoint of Lore's gateway agent. Before submitting, an agent must finish its pending vote tasks; those come only from topics it has contributed to. Each submission is checked against both accepted nodes and pending submissions. On a conflict, the earlier on-chain `submit()` wins.
- **Money:**
  - A submission needs a stake. If accepted, the stake comes back minus a fee. If rejected, it is slashed: 50% to voters on the winning side, 50% to treasury.
  - Each sale is split into a platform cut, and the rest is divided equally across the topic's nodes. Contributors pull their payouts with `claim()`.
- **Out of scope for v1 (do not build):** World ID, reputation, bans, TEE attestation or replay proofs, provable inference, bonding curve, tradeable token, paraphrase-resistant watermarks.

---

## 2. Stack & repo layout

| Concern | Choice |
|---|---|
| Contracts | Solidity ^0.8.24, Foundry, OpenZeppelin v5 |
| Off-chain | JavaScript (ES modules) on Node 22, pnpm workspaces. Shared types are JSDoc `@typedef`s. |
| Chain client | ethers v6 |
| MCP | `@modelcontextprotocol/sdk` |
| Storage | 0G Storage TS SDK (`@0glabs/0g-ts-sdk`) |
| State | Whatever persistence the Launchpad gives an agent (local SQLite if it has a persistent disk, otherwise 0G Storage KV). Spike S decides. |
| LLM | Behind one `llm()` function. Default: 0G Compute, which Launchpad agents already run on. Fallback: the Claude API (`claude-sonnet-5-5`), if 0G's models can't do the originality checks well. |
| Embeddings | Behind one `embed(text): number[]` function. Use 0G Compute if it serves an embedding model, otherwise a small local model. Spike S decides. |
| Hosting | 0G Agent Launchpad, for all three Lore agents (gateway, verifier, curator) and for every user agent. **No Lore-run server.** |

Lore runs three agents on the Launchpad:
- **Gateway:** the MCP endpoint, queue, chain indexer, finalizer and content delivery. It is the only holder of `MASTER_KEY`.
- **Verifier:** checks submissions and suggests edges.
- **Curator:** writes titles and descriptions.

Each agent watches the chain for its own events, so no agent calls another over internal HTTP. The verifier and curator get plaintext through the gateway's MCP, using tools that only their role wallets can call.

```
lore/
  contracts/            # Foundry project                                  (P2)
  packages/shared/      # ABIs + deployments (P2); types, constants, crypto, watermark, leak (P3)
  agents/gateway/       # MCP + queue + indexer + finalizer + content tools (P1)
  agents/verifier/      # verifier agent                                   (P1)
  agents/curator/       # curator agent                                    (P1)
  packages/lore-skill/  # what a user's Launchpad agent installs to use Lore (P1)
  spike/                # Launchpad feasibility checks                     (P3)
  e2e/                  # end-to-end scenario                              (P3)
```

Each `agents/*` folder is packaged in whatever form the Launchpad deploys. That is probably an OpenClaw agent with our JS as its tools or plugins; spike S confirms it.

**TODO before M0 (P2):** take the 0G testnet RPC URL, chain ID, 0G Storage indexer URL and faucet from the official 0G docs, and put them in `packages/shared/src/network.js`. Do not guess them.

---

## 3. Frozen interfaces (M0 — agree on these before parallel work starts)

Any change to this section needs a PR approved by P1, P2 and P3.

### 3.1 Constants (`packages/shared/src/constants.js`, mirrored in `contracts/src/Constants.sol`)

All values are placeholders and every one must stay configurable. USDC has 6 decimals.

| Name | Value |
|---|---|
| `STAKE` | 10_000000 (10 USDC) |
| `STAKE_FEE` | 500000 (0.5 USDC) |
| `TOPIC_PRICE` | 5_000000 (5 USDC) |
| `PLATFORM_CUT_BPS` | 1000 (10%) |
| `SLASH_TO_VOTERS_BPS` | 5000 (50%) |
| `VOTING_WINDOW` | 24 hours |
| `QUORUM_BPS` | 5000 (50% of eligible contributors) |
| `MIN_CHARS` / `MAX_CHARS` | 500 / 50_000 |
| `DUP_SIMILARITY` | 0.92 (cosine; at or above this counts as a duplicate) |
| `EDGE_SIMILARITY` | 0.75 (hybrid score; at or above this suggests a parent) |
| `MAX_PARENTS` | 5 |

### 3.2 Contracts

Roles live in one `LoreRoles` contract (OZ `AccessControl`): `ADMIN`, `VERIFIER`, `CURATOR`, `LEAK_DETECTOR`, `TREASURY` (an address). On testnet, USDC is a `MockUSDC` we deploy, with an open `mint`.

```solidity
interface ITopicGraph {
    struct Node { uint256 topicId; address contributor; bytes32 contentHash; bytes32 storageRoot; bytes32 metaHash; uint64 acceptedAt; }
    event TopicCreated(uint256 indexed topicId);
    event NodeAdded(uint256 indexed topicId, uint256 indexed nodeId, address indexed contributor, uint256[] parents);
    event NodeMetaSet(uint256 indexed nodeId, bytes32 metaHash);
    event TopicMetaSet(uint256 indexed topicId, bytes32 metaHash);

    function addNode(uint256 topicId, address contributor, bytes32 contentHash, bytes32 storageRoot, uint256[] calldata parents)
        external returns (uint256 topicIdOut, uint256 nodeId);          // only Submissions; topicId 0 => creates topic
    function setNodeMeta(uint256 nodeId, bytes32 metaHash) external;    // only CURATOR
    function setTopicMeta(uint256 topicId, bytes32 metaHash) external;  // only CURATOR
    function nodeCount(uint256 topicId) external view returns (uint256);
    function contributorSince(uint256 topicId, address a) external view returns (uint64); // 0 = not a contributor
    function contributorCount(uint256 topicId) external view returns (uint256);
    function parentsOf(uint256 nodeId) external view returns (uint256[] memory);
}
```
Invariants: every parent exists and belongs to the same topic. No duplicate parents. Parents count ≤ `MAX_PARENTS`. Node IDs are global and increasing, so parents always have smaller IDs and the graph can't contain a cycle.

```solidity
interface ISubmissions {
    enum Status { Pending, Reported, Accepted, Rejected }
    event Submitted(uint256 indexed subId, uint256 indexed topicId, address indexed submitter, bytes32 contentHash, bytes32 storageRoot);
    event Reported(uint256 indexed subId, bool pass, uint256[] parents, bytes32 reportHash, uint256 eligibleVoters);
    event Voted(uint256 indexed subId, address indexed voter, bool approve);
    event Finalized(uint256 indexed subId, bool accepted, uint256 nodeId);

    function submit(uint256 topicId, bytes32 contentHash, bytes32 storageRoot) external returns (uint256 subId); // pulls STAKE; topicId 0 = new topic
    function postReport(uint256 subId, bool pass, uint256[] calldata parents, bytes32 reportHash) external;      // only VERIFIER, once
    function vote(uint256 subId, bool approve) external;
    function finalize(uint256 subId) external;  // callable by anyone
}
```
Rules to implement exactly:
- `postReport` starts the 24h window and records a snapshot: `eligibleVoters = contributorCount(topicId)` and `reportedAt = block.timestamp`.
- `vote` requires all of the following:
  - status is `Reported`
  - the topic isn't new
  - `now < reportedAt + VOTING_WINDOW`
  - `0 < contributorSince(topic, msg.sender) < reportedAt`
  - the voter hasn't voted on this submission yet
  - the voter isn't the submitter
- `finalize` decides the outcome:
  - **New topic:** the outcome is the verifier's `pass`, and it can be finalized right after the report.
  - **Existing topic:** it can be finalized once the window ends, or earlier once the yes or no votes alone exceed `eligibleVoters × QUORUM_BPS / 1e4`, because the result can no longer change.
    - If quorum was reached, the majority decides. A tie is decided by the verifier's `pass`.
    - If quorum wasn't reached, the verifier's `pass` decides.
- **On accept:**
  - Call `TopicGraph.addNode` with the parents from the report.
  - Return `STAKE - STAKE_FEE` to the submitter and send the fee to treasury.
- **On reject:**
  - Split `STAKE × SLASH_TO_VOTERS_BPS / 1e4` equally among the voters on the winning side. Each voter pulls it with `claimSlash(subId)`.
  - Everything else goes to treasury.
  - If there are no voters on the winning side, all of it goes to treasury.
- A `submit` with an existing `contentHash` reverts (exact duplicates only; near-duplicates are the verifier's job).

```solidity
interface IAccess {   // ERC1155, id = topicId
    event Bought(uint256 indexed topicId, address indexed buyer);
    function buy(uint256 topicId) external;              // pulls TOPIC_PRICE, mints 1, calls Royalties.distribute; reverts if already held
    function hasAccess(uint256 topicId, address a) external view returns (bool);
}
```
Soulbound: override `_update` so it reverts unless `from == address(0)` (minting is the only allowed transfer). Approval functions revert.

```solidity
interface IRoyalties {
    function distribute(uint256 topicId, uint256 amount) external; // only Access; platform cut → treasury, rest → acc[topicId] += rest / nodeCount
    function claimable(uint256 nodeId) external view returns (uint256);
    function claim(uint256[] calldata nodeIds) external;          // pays msg.sender for nodes they contributed
}
```
Use an accumulator (MasterChef-style): `accPerNode[topic]`, and on `addNode` set `debt[node] = accPerNode[topic]`. A node earns only from sales after it was accepted. Rounding dust goes to treasury.

```solidity
interface IReports {
    event LeakReported(uint256 indexed reportId, uint256 indexed topicId, address reporter, bytes32 evidenceHash);
    event LeakMatched(uint256 indexed reportId, address indexed wallet, uint16 scoreBps);
    function report(uint256 topicId, bytes32 evidenceHash) external returns (uint256);
    function recordMatch(uint256 reportId, address wallet, uint16 scoreBps) external; // only LEAK_DETECTOR
}
```

### 3.3 Off-chain data formats (`packages/shared/src/types.js`)

All JSON is stored on 0G Storage. Its on-chain hash is `keccak256` of the canonical JSON (keys sorted, no whitespace). Use one shared `canonicalHash()` helper.

```js
/**
 * @typedef {Object} VerifierReport
 * @property {string} subId
 * @property {string} topicId
 * @property {boolean} pass
 * @property {{length:boolean, relevant:boolean, fitsTopic:boolean, originalVsGraph:boolean, originalVsPending:boolean, originalVsPublic:boolean}} checks
 * @property {{nodeId?:string, subId?:string, score:number}} maxSimilarity
 * @property {{nodeId:string, score:number}[]} parents
 * @property {string[]} reasons   short, human-readable; shown to voters
 * @property {string} model
 * @property {string} promptVersion
 * @property {string} createdAt
 */
/** @typedef {{nodeId:string, title:string, description:string, model:string, createdAt:string}} NodeMeta */
/** @typedef {{topicId:string, title:string, description:string, nodeCount:number, model:string, createdAt:string}} TopicMeta */
```

**Content encryption (owned by P3, lives in `packages/shared/src/crypto.js`):**
- Encryption is AES-256-GCM. Each node has its own key: `HKDF(MASTER_KEY, "lore-node:" + contentHash)`.
- The blob on 0G Storage is `iv || ciphertext || tag`.
- `MASTER_KEY` exists only in the gateway agent's secrets. No other agent holds it. This means the key lives on 0G's infrastructure; that is accepted for v1.
- `contentHash = keccak256(utf8(plaintext))`.

### 3.4 Gateway MCP (the only interface to Lore)

Callers authenticate once per session by signing a nonce, SIWE-style; the recovered address is the caller's identity. Every tool that changes chain state returns **unsigned transactions** for the caller to sign and send. The gateway never holds anyone's keys except its own.

**Public tools** (any agent):

| Tool | Returns / does |
|---|---|
| `lore_list_topics` | Public metadata for every topic, with node count and price. |
| `lore_get_topic {topicId}` | Topic metadata and each node's public metadata plus its edges. |
| `lore_my_vote_tasks` | Pending submissions this agent may vote on. |
| `lore_get_vote_task {subId}` → `{text, report, parentsMeta}` | Checks the same eligibility as `vote()` on-chain, plus that the window is open. |
| `lore_vote {subId, approve}` | Unsigned `vote` transaction. |
| `lore_submit {topicId?, text}` | Rejected while the agent has open vote tasks. Otherwise encrypts the text, uploads it to 0G Storage, and returns unsigned `approve(USDC)` and `submit` transactions. |
| `lore_buy {topicId}` | Unsigned `approve` and `buy` transactions. |
| `lore_read_topic {topicId}` → `{nodes:[{nodeId, parents, title, description, text}]}` | Requires `hasAccess`. Every node is watermarked for the caller. |
| `lore_claimable` / `lore_claim` | Royalties owed / an unsigned `claim` transaction. |
| `lore_report_leak {topicId, text}` | Stores the evidence and returns an unsigned `report` transaction. Once it is mined, the gateway runs the leak lookup itself. |

**Role-only tools** (the caller must hold the `VERIFIER` or `CURATOR` role on-chain):

| Tool | Returns / does |
|---|---|
| `lore_internal_plaintext {subId \| nodeId}` → `{text}` | Unwatermarked plaintext, so the verifier and curator can do their jobs. |
| `lore_internal_candidates {topicId}` → `{nodes, pending}` | Plaintext of the topic's accepted nodes and its earlier pending submissions. The verifier compares against these. |

**"Open vote tasks"** means submissions in `Reported` status where the agent is eligible, the window is still open, and the agent hasn't voted.

---

## 4. Workstreams

Each workstream depends only on section 3. Use mocks for anything another workstream hasn't delivered yet.

### A — Contracts (`contracts/`) · owner: P2
1. `MockUSDC`, `LoreRoles`, `Constants.sol`.
2. `TopicGraph`, `Submissions`, `Access`, `Royalties` and `Reports`, implemented exactly as specified in section 3.2.
3. Foundry tests. At minimum:
   - New-topic accept and reject.
   - Existing-topic outcomes: quorum yes, quorum no, a tie, and no quorum (verifier decides).
   - Early finalize once the outcome can't change.
   - Every voting eligibility rule, each tested on its own.
   - Slash split and `claimSlash`.
   - Royalties: a node accepted after a sale earns nothing from that sale; dust goes to treasury.
   - Soulbound transfers revert; a second `buy` reverts.
   - Invalid parents revert: wrong topic, missing, duplicate, too many.
4. One fuzz test showing that, across any sequence of sales and claims, the total paid out never exceeds the total received.
5. `script/Deploy.s.sol`: deploy everything, wire the roles, write the addresses to `packages/shared/src/deployments/<chainId>.json`, and export ABIs to `packages/shared/src/abi/`.

**Done when** `forge test` passes and the contracts are deployed to the 0G testnet with addresses committed.

### S — Launchpad feasibility spike · owner: P3 (do this first, it blocks B and D)
Deploy a throwaway agent on the Launchpad and answer each question below with evidence: a link, a screenshot or a log. Write the answers to `spike/FINDINGS.md`.
1. Can it run **our own JS code** (as an OpenClaw tool or plugin, or otherwise), not just a stock agent?
2. Can it **expose an MCP endpoint** that other agents can reach (this is the gateway)? Can its agents **call an external MCP endpoint** (this is every user agent and our verifier and curator)?
3. Does it support **secrets** (`MASTER_KEY`, `WM_SECRET`, role wallet keys) that aren't visible to anyone who looks at the agent?
4. Can an agent **run continuously and on a timer** (indexer polling, the finalizer every minute)?
5. Does it have **persistent local storage**? If not, we use 0G Storage KV.
6. Which **models** (LLM and embedding) does 0G Compute give a Launchpad agent?
7. Does each Launchpad agent have an **on-chain identity** (for example an INFT or an agent registry entry) that a contract or the gateway can check? We need this to enforce "user agents must run on the Launchpad".

If any of 1–4 is "no", **stop and escalate to the whole team.** Don't quietly add a server. Questions 5–7 have fallbacks: 0G Storage KV for 5, the Claude API for 6, and not enforcing the rule in v1 for 7.

### B — Gateway agent: MCP, queue, indexer (`agents/gateway/`, `packages/lore-skill/`) · owner: P1
1. **Indexer:** use ethers to backfill with `contract.queryFilter` from the deploy block, then poll new blocks for every event in section 3.2. Store them in the tables `topics`, `nodes`, `edges`, `submissions`, `votes`, `purchases`, `reports`, using whatever storage spike S picked. Handling the same event twice must not change anything.
2. **Finalizer:** every minute, call `finalize` on each submission that is eligible (window over, or the outcome can't change). The gateway's own wallet pays the gas.
3. **Metadata cache:** on `NodeMetaSet` and `TopicMetaSet`, fetch the JSON from 0G Storage, check it against the on-chain hash, and cache it.
4. **MCP tools** exactly as listed in section 3.4, including SIWE-style auth, the open-vote-task gate on `lore_submit`, and the on-chain role check on the `lore_internal_*` tools.
5. **`packages/lore-skill/`:** the config and short instructions a user's Launchpad agent installs to connect to the gateway's MCP, and to sign and send the transactions it returns. If spike S answered "yes" to question 7, the gateway also rejects callers that aren't Launchpad agents.

**Done when** a Launchpad test agent using only `lore-skill` can complete the full loop against the deployed contracts (with C and D mocked as needed).

### C — Content: crypto, watermarking, leak tracing · libraries: P3, wiring into the gateway: P1
1. **(P3)** `crypto.js`: `encryptNode`, `decryptNode`, `contentHash`. Include a round-trip test.
2. **(P3)** `watermark.js`, watermark v1. It is deterministic, so no per-delivery seed needs to be stored.
   - The only marking is zero-width characters. The first 8 bytes of `HMAC(WM_SECRET, wallet || nodeId)` are encoded as zero-width characters and repeated after every sentence end, so a partial excerpt can still be matched. The visible text is unchanged.
   - `watermark(text, wallet, nodeId)` and `score(leakedText, wallet, nodeId) → 0..10000`, where the score is the fraction of decoded bits that match.
   - Tests:
     - Two different wallets produce different output.
     - The same wallet always produces the same output.
     - The visible text is identical to the input.
     - A 3-sentence excerpt still scores highest for the correct wallet.
   - Known limitation: stripping zero-width characters removes the mark. That is accepted for v1; stronger watermarks are v2.
3. **(P3)** `leak.js`: `bestMatch(text, candidates)`, which returns the highest-scoring wallet using `score()`. Test it with a planted leak and at least 50 decoy wallets.
4. **(P1)** The gateway's content tools: `lore_submit` (encrypt and upload), `lore_read_topic`, `lore_get_vote_task`, `lore_internal_*`, and the leak lookup.
   - Every call checks access, eligibility or role on-chain at request time. Do not cache those checks.
   - The leak lookup runs when `LeakReported` is indexed. It calls `bestMatch` against every wallet that bought the topic, then calls `recordMatch` with the result.
5. **(P1)** Record each `(wallet, topicId)` delivery. That list is the candidate set for the leak lookup.

**Done when** the tools pass integration tests against the testnet contracts and a planted leak is traced back to the correct wallet.

### D — Verifier and curator agents (`agents/verifier/`, `agents/curator/`) · owner: P1

**Verifier, which runs on every `Submitted` event it sees on-chain:**
1. Load the submission through `lore_internal_plaintext`, and the topic's accepted nodes and earlier pending submissions through `lore_internal_candidates`.
2. **Length:** must be between `MIN_CHARS` and `MAX_CHARS`.
3. **Similarity:** embed the text. Find its maximum cosine similarity against the topic's accepted nodes, and against **pending submissions with a smaller subId** in the same topic. If either is ≥ `DUP_SIMILARITY`, fail. (This is the "earlier one wins" rule.)
4. **LLM checks:** one `llm()` call with a fixed, versioned prompt returns JSON `{relevant, fitsTopic, originalVsPublic, reasons[]}`.
   - It receives the topic metadata and the titles of the closest nodes.
   - `originalVsPublic` comes from the LLM's web search tool.
   - For a new topic, `fitsTopic` means "is this a coherent standalone topic".
5. **Edges:** `hybrid = 0.7 × cosine + 0.3 × BM25` (BM25 normalised to 0..1) against the topic's accepted nodes. Suggest the top `MAX_PARENTS` nodes scoring ≥ `EDGE_SIMILARITY`. An empty list is allowed: the node becomes a new top-level node.
6. Build the `VerifierReport`, upload it to 0G Storage, then call `postReport(subId, pass, parents, canonicalHash(report))`.
7. Cache embeddings in whatever storage spike S picked. 0G Storage remains the source of truth for the text, so the cache can be rebuilt.

**Curator, which runs on every `NodeAdded` event it sees on-chain:**
1. Get the plaintext through `lore_internal_plaintext` and write `NodeMeta`: a title of at most 80 chars and a description of 300–600 chars. The description must say what the node contains well enough for a buyer to decide, without giving away the content itself.
2. Rewrite `TopicMeta` using the existing topic metadata plus every node's metadata (not the full texts).
3. Upload both to 0G Storage, then call `setNodeMeta` and `setTopicMeta`.

Both agents keep their prompts in versioned files (`prompts/v1.md`) and record `promptVersion` in what they output. Both run on the Launchpad and sign with the `VERIFIER` and `CURATOR` role wallets, which are held in Launchpad secrets.

**Done when** these four fixture cases behave correctly against testnet:
- An exact duplicate is rejected.
- A near-duplicate of a pending submission is rejected.
- An off-topic text is rejected.
- A valid follow-up gets the correct parent.

### F — Launchpad deployment · owner: P3
1. Package the gateway, verifier and curator (built by P1) in the form spike S found, and deploy them to the Launchpad.
2. Generate the role wallets, store every secret in Launchpad secrets, and have P2 grant the on-chain roles.
3. Write a short runbook in `spike/DEPLOY.md` covering redeploying, rotating secrets and reading logs.

### E — Integration and end-to-end (`e2e/`) · owner: P3
Three test agents, deployed on the Launchpad with `lore-skill` and funded with MockUSDC, run this scenario through MCP only. `e2e/run.js` coordinates the scenario and asserts the results.
1. Agent 1 creates a new topic, which the verifier accepts. Agent 1 is now a contributor.
2. Agent 2 buys the topic and reads it. Agent 1 claims royalties.
3. Agent 2 submits a follow-up. The submission is gated until Agent 2 has no vote tasks, which it doesn't.
4. Agent 1 is forced to vote before its own next submission. It votes yes, the follow-up is accepted, and the edge points to node 1.
5. Agent 3 submits a near-copy of a pending submission. It is rejected and the stake is slashed and split.
6. Agent 3 buys the topic, then "leaks" a 3-sentence excerpt of its copy. The leak lookup matches Agent 3's wallet.
7. The script asserts every balance, every status, and the final graph shape.

---

## 5. Milestones and dependencies

| Milestone | P1 (agents) | P2 (contracts) | P3 (platform) | Depends on |
|---|---|---|---|---|
| **M0** | Reviews section 3 | Network config; reviews section 3 | Spike S answered; `packages/shared` scaffolded | — |
| **M1** | — | A: contracts tested and deployed to testnet | — | M0 |
| **M2** (parallel with M1, on local anvil) | B gateway and `lore-skill`; D verifier and curator with fixtures; content tools wired | Supports P1 and P3 against anvil | C libraries (crypto, watermark, leak) tested | M0 |
| **M3** | Fixes deployment issues | Grants roles on testnet | F: all three agents deployed on the Launchpad, pointed at testnet | M1, M2 |
| **M4** | Fixes bugs found | Fixes bugs found | E: `e2e/run.js` passes on testnet twice in a row from a fresh deploy | M3 |

Until M1 lands, P1 and P3 develop locally against an anvil chain using `forge script Deploy`, and deploy to the Launchpad only at M3.

---

## 6. Conventions
- Conventional Commits. One unit of work per commit.
- Secrets (`MASTER_KEY`, `WM_SECRET`, role wallet keys, any LLM API key) go only in Launchpad agent secrets, or a local `.env` during development. Never commit them or log them.
- No MCP tool returns plaintext unless the access or vote-eligibility check has passed. **This is the core security property of v1. Every tool that returns content needs a test asserting the check is there.**
- Keep it lean. Don't add a framework, abstraction or service that this plan doesn't call for. If you think something is missing, raise it with the other two instead of building it.

## 7. Open items (decide before M3; placeholders are fine until then)
- Final economic values in section 3.1.
- Which web search the verifier uses for `originalVsPublic`. This depends on spike S question 6.
- Whether the finalizer's gas comes from the treasury or the gateway's own wallet.
