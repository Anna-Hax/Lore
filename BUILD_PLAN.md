# Lore v1 — Build Plan

Audience: the coding agents (and their humans) building Lore v1. Read this whole file before starting your workstream. Product spec: https://claude.ai/artifact/KvzhXcdgHuhuBvokj7iKbf

**Goal of v1:** the full marketplace loop running end to end on the 0G testnet. An agent submits research, it gets verified and voted on, it becomes a node in a topic graph, another agent buys the topic and reads a watermarked copy, and contributors claim royalties. Every model call Lore's agents make carries a visible, independently checkable 0G proof.

---

## 0. Team split (3 people)

| Person | Role | Owns | Paths |
|---|---|---|---|
| **P1** | Agent developer | B (the hosted gateway: MCP server with World ID login, internal API, queue, indexer, finalizer) and D (verifier and curator, including 0G Compute proofs) | `agents/*` |
| **P2** | Blockchain developer | A (all contracts, tests, deploy script, ABI export, testnet deploys, network config) | `contracts/`, `shared/lore_shared/{abi,deployments,network.py}` |
| **P3** | Platform and integration | S (0G Compute and Storage spike), C libraries (crypto, watermark, leak scoring, 0G Storage client), the `shared` package scaffold and types, hosting and deploying our agents (F), E (end-to-end) | `spike/`, `shared/lore_shared/{crypto,watermark,leak,storage,types,constants,canonical}.py`, `deploy/`, `e2e/` |

Handoffs:
- **P2 → P1, P3:** ABIs and deployment addresses in `shared`. Use the local anvil deploy until testnet is ready.
- **P3 → P1:** pure, tested libraries: `crypto.py`, `watermark.py`, `leak.py`, which provides `best_match(text, candidates) → (wallet, ref, score_bps)` (section C), and `storage.py`, the 0G Storage upload and download wrapper. P1 wires them in; P3 never edits `agents/*`.
- **P3 → everyone:** spike findings. They pin down how we call 0G Compute and 0G Storage from Python.
- **Section 3 (frozen interfaces):** a change needs approval from all three.

---

## 1. Product rules (the parts you need to code against)

- **Topic:** one commit graph, which is a DAG of nodes. A node can have 0..n parents, and a topic can have several top-level nodes.
- **Node:** encrypted text plus public metadata (title and description). Only Lore's curator agent writes metadata; the submitter never does.
- **Access:** only `buy(topicId)` grants access. The price is fixed and paid in USDC. The token is a soulbound ERC-1155 (non-transferable), one token ID per topic. Access is permanent and includes nodes added later. Contributing never grants access.
- **Identity (World ID):**
  - Every agent that submits or votes must be linked to a real person through World ID (Orb or device level). Buying and reading stay open to anyone.
  - One person can run many agents. World ID can't be verified on 0G, so the gateway verifies each proof with World's API (the proof's signal is the agent's address) and records agent → person in `PersonRegistry`. The person id is World ID's nullifier for Lore's action.
- **Voting:**
  - **One vote per person, not per agent.** A person who contributed to the topic (through any of their agents) before the report can vote once, from any one of their agents. Nobody votes on a submission made by one of their own agents.
  - A voter sees four things: the submission text, the verifier report, the verifier's 0G proofs, and the public metadata of the suggested parents. Nothing else.
  - The voting window is 24h. If quorum isn't reached, the verifier's verdict stands.
  - On a **new topic**, the verifier is the only voter.
- **Where things run:**
  - **User agents** are the user's own agents (any MCP-capable client: Claude Code, Cursor, ...). They connect to **Lore's hosted MCP server** at `{LORE_PUBLIC_URL}/mcp`.
  - **Login is the user's World ID, and nothing else.** The MCP server uses standard MCP OAuth: on first connect the client opens Lore's `/login` page, the user approves in World App, and the client gets a token whose subject is their person (the World ID nullifier for Lore's action, the same id `PersonRegistry` uses). There is no wallet login.
  - **Wallets: Turnkey with delegated access.** `lore_create_wallet` gives each person a wallet in their own Turnkey sub-organization. The user is its only root (reachable by their email) and can revoke Lore at any time. Lore's delegated key may sign only Lore's calls on Lore's chain: USDC `approve` with Lore's Submissions or Access contract as spender, plus `submit`, `vote`, `buy`, `claim` and `report`, enforced by Turnkey's policy engine. The policies also require zero native value and cap gas per transaction. They limit where funds can go (only Lore's contracts), not how much: whoever holds the delegated key can spend the wallet on Lore actions, so users keep only what they mean to spend on Lore. The gateway links the new wallet to the person in `PersonRegistry`. The user funds it with 0G (gas) and USDC.
  - **Demo login.** Without a registered World app, a gateway started with `LORE_DEMO_LOGIN=1` offers a clearly labelled name-based login (testnet demos only); it is refused whenever World ID is configured.
  - **Lore's agents** (gateway with the MCP server, verifier, curator) are hosted by us. The verifier and curator reach the gateway's internal API with a shared service secret.
- **Gate:** before submitting, an agent must finish its pending vote tasks; those come only from topics it has contributed to.
  - The gateway enforces this when a submission is prepared (`lore_submit`), per person across all their wallets.
  - Each submission is checked against both accepted nodes and pending submissions. On a conflict, the earlier on-chain `submit()` wins.
- **Money:**
  - A submission needs a stake. If accepted, the stake comes back minus a fee. If rejected, the whole stake goes to the treasury. Voters are never paid for voting, so no vote can be bought.
  - Each sale is split into a platform cut, and the rest is divided equally across the topic's nodes. Contributors pull their payouts with `claim()`.
- **Model proofs:** every model call by Lore's agents runs on 0G Compute as a verified, private run with a stored proof (section 2.1). Users can see each proof and check it themselves.
- **Out of scope for v1 (do not build):** reputation, bans, provable inference (zk), bonding curve, tradeable token, paraphrase-resistant watermarks.

---

## 2. Stack & repo layout

| Concern | Choice |
|---|---|
| Contracts | Solidity ^0.8.24, Foundry, OpenZeppelin v5 |
| Off-chain | **Python 3.12**, `uv` workspace, `pytest` |
| Chain client | `web3.py` v7 + `eth-account` |
| Gateway API | FastAPI + uvicorn |
| MCP server | Official `mcp` Python SDK (`MCPServer`, streamable HTTP), hosted inside the gateway, with the SDK's OAuth 2.1 server and World ID as the login. |
| Models | 0G Compute Router, `https://router-api.0g.ai/v1`, called with the `openai` Python client. 0G has no official Python SDK, so we call the router directly. |
| Embeddings | A TeeML embedding model on the 0G Router if one exists; otherwise a local model (`fastembed`, `bge-small`), which keeps the text on our host. Spike S decides. |
| Storage | 0G Storage. The Python route (an SDK, or the official CLI called via subprocess) is decided by spike S and wrapped in `lore_shared.storage`. |
| Local state | `sqlite3` (stdlib), one file per agent |
| Crypto | `cryptography` (AES-GCM, HKDF) |
| Hosting | Lore's three agents run on our own host (provider decided by P3). Users' agents connect to the hosted MCP server. |

```
lore/
  contracts/            # Foundry project                                    (P2)
  shared/lore_shared/   # ABIs + deployments + network (P2); types, constants, crypto,
                        #   watermark, leak, storage, canonical (P3)
  agents/gateway/       # hosted MCP + World ID login + internal API + indexer (P1)
  agents/verifier/      # verifier agent                                      (P1)
  agents/curator/       # curator agent                                       (P1)
  agents/zg/            # 0G Compute client + proof receipts, used by both    (P1)
  spike/                # 0G Compute and Storage feasibility checks           (P3)
  deploy/               # hosting config for our three agents                 (P3)
  e2e/                  # end-to-end scenario                                 (P3)
```

**TODO before M0 (P2):** take the 0G testnet RPC URL, chain ID, 0G Storage indexer URL and faucet from the official 0G docs, and put them in `shared/lore_shared/network.py`. Do not guess them.

### 2.1 0G Compute: verified runs, privacy on demand, proof of model

This is a headline feature, not plumbing. Every model call from the verifier and curator (and any future Lore agent) goes through **one function**, `agents/zg.call(model, messages, *, private=True) → (output, receipt)`. Nothing calls a model any other way.

Each call does all of the following:
1. **Privacy on demand.**
   - When `private=True`, send the header `X-0G-Provider-Trust-Mode: private`. The request then routes only to TeeML providers, where the model runs inside a TEE, the prompt enters the enclave encrypted, and nothing is retained.
   - **Any call that contains submission or node text must be private.** Our API key is also created with `trust_mode: "private"`, so a code bug can't downgrade privacy.
   - If no private provider is available, the router returns a `503` with `no_provider_for_trust_mode`. Retry with backoff. **Never fall back to a lower trust tier.**
   - Use only models the router's `/v1/models` lists with `"verifiability": "TeeML"`.
2. **Verified run.** Send `verify_tee: true` in the request body. Read `x_0g_trace.tee_verified`; `false` is a hard failure, and the result is not used. The live Router omits the field (spike S1), so our own signer check in step 3 is the verdict. Record `x_0g_trace.provider`.
3. **Proof of which model produced the result.** Don't rely on the router's flag alone; verify it ourselves.
   1. Take the `chatID` from the `ZG-Res-Key` response header, falling back to the body's `id`.
   2. Fetch `GET {provider_url}/v1/proxy/signature/{chatID}?model={model}`, which returns `{text, signature}`.
   3. Recover the signer with EIP-191 `personal_sign`.
   4. Check that the signer equals the provider's on-chain `teeSignerAddress`, or `additionalInfo.targetTeeAddress` when `targetSeparated` is true.
   5. Check that `text` matches the output we received — or, because the Router always end-to-end encrypts private requests (spike S2), that it is the `zg-sig-v1/e2ee-ct:<request hash>:<response hash>` form. Record which in the receipt's `binding`.
4. **Keep the evidence.** Build an `InferenceReceipt` (section 3.3), upload it to 0G Storage, and put its hash inside whatever the output feeds: the `VerifierReport`, `NodeMeta` or `TopicMeta`. That ties it to the on-chain hash.
5. **Make it visible.**
   - The MCP tools show the model, provider, a "TEE verified" mark and a "private" mark next to every verifier verdict and every title and description.
   - `lore_check_proof` re-runs step 3 against 0G's on-chain record of the provider. Since the MCP server is hosted, this check runs on Lore's server; a user who doesn't want to trust Lore can repeat it with any EIP-191 tool, because the receipt, signature and the on-chain record are all public.
6. **Attest the providers we use.** P3 runs `0g-compute-cli inference verify --provider <addr>` daily for every provider seen in receipts, and publishes the output to 0G Storage. That check covers the provider's signer address and its deployment configuration hash.
7. **Make runs repeatable.** Use `temperature=0` and versioned prompts, and record the prompt version in every receipt.

Be honest about the limit: the proof shows that a TEE-attested provider, which registered on-chain as serving `model`, handled the request privately and signed it. With E2EE (every Router call today) the TEE signs hashes of the encrypted exchange, so the signature does not bind the plaintext output; the model name is not inside the signed text either. Say exactly this in the user-facing docs.

---

## 3. Frozen interfaces (M0 — agree on these before parallel work starts)

Any change to this section needs a PR approved by P1, P2 and P3.

### 3.1 Constants (`shared/lore_shared/constants.py`, mirrored in `contracts/src/Constants.sol`)

All values are placeholders and every one must stay configurable. USDC has 6 decimals.

| Name | Value |
|---|---|
| `STAKE` | 10_000000 (10 USDC) |
| `STAKE_FEE` | 500000 (0.5 USDC) |
| `TOPIC_PRICE` | 5_000000 (5 USDC) |
| `PLATFORM_CUT_BPS` | 1000 (10%) |
| `VOTING_WINDOW` | 24 hours |
| `QUORUM_BPS` | 5000 (50% of eligible contributors) |
| `MIN_CHARS` / `MAX_CHARS` | 500 / 50_000 |
| `DUP_SIMILARITY` | 0.92 (cosine; at or above this counts as a duplicate) |
| `EDGE_SIMILARITY` | 0.75 (hybrid score; at or above this suggests a parent) |
| `MAX_PARENTS` | 5 |

### 3.2 Contracts

Roles live in one `LoreRoles` contract (OZ `AccessControl`): `ADMIN`, `VERIFIER`, `CURATOR`, `LEAK_DETECTOR`, `REGISTRAR` (the gateway: records agent → person), `TREASURY` (an address). On testnet, USDC is a `MockUSDC` we deploy, with an open `mint`.

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
    function personSince(uint256 topicId, bytes32 person) external view returns (uint64); // 0 = not a contributor
    function personCount(uint256 topicId) external view returns (uint256); // distinct people: the voter base
    function parentsOf(uint256 nodeId) external view returns (uint256[] memory);
}
```
Invariants: every parent exists and belongs to the same topic. No duplicate parents. Parents count ≤ `MAX_PARENTS`. Node IDs are global and increasing, so parents always have smaller IDs and the graph can't contain a cycle.

```solidity
interface ISubmissions {
    enum Status { Pending, Reported, Accepted, Rejected }
    event Submitted(uint256 indexed subId, uint256 indexed topicId, address indexed submitter, bytes32 contentHash, bytes32 storageRoot);
    event Reported(uint256 indexed subId, bool pass, uint256[] parents, bytes32 reportHash, uint256 eligibleVoters);
    event Voted(uint256 indexed subId, address indexed voter, bytes32 indexed person, bool approve); // one vote per person
    event Finalized(uint256 indexed subId, bool accepted, uint256 nodeId);

    function submit(uint256 topicId, bytes32 contentHash, bytes32 storageRoot) external returns (uint256 subId); // pulls STAKE; topicId 0 = new topic
    function postReport(uint256 subId, bool pass, uint256[] calldata parents, bytes32 reportHash) external;      // only VERIFIER, once
    function vote(uint256 subId, bool approve) external;
    function finalize(uint256 subId) external;  // callable by anyone
}
```
Rules to implement exactly:
- `submit` reverts with `NotRegistered` unless `PersonRegistry.personOf(msg.sender)` is set, and `addNode` requires every contributor to be registered.
- `postReport` starts the 24h window and records a snapshot: `eligibleVoters = personCount(topicId)` (people, not agents) and `reportedAt = block.timestamp`.
- `vote` works out `person = personOf(msg.sender)` and requires all of the following:
  - status is `Reported`
  - the topic isn't new
  - `now < reportedAt + VOTING_WINDOW`
  - `person` is set, and `0 < personSince(topic, person) < reportedAt`
  - this person hasn't voted on this submission yet, from any of their agents (`voteOf[subId][person]`)
  - this person isn't the submitter's person
- `finalize` decides the outcome:
  - **New topic:** the outcome is the verifier's `pass`, and it can be finalized right after the report.
  - **Existing topic:** it can be finalized once the window ends, or earlier once the yes or no votes alone exceed `eligibleVoters × QUORUM_BPS / 1e4`, because the result can no longer change.
    - If quorum was reached, the majority decides. A tie is decided by the verifier's `pass`.
    - If quorum wasn't reached, the verifier's `pass` decides.
- **On accept:**
  - Call `TopicGraph.addNode` with the parents from the report.
  - Return `STAKE - STAKE_FEE` to the submitter and send the fee to treasury.
- **On reject:** the whole stake goes to treasury. Voters receive nothing, whichever way they voted.
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

```solidity
contract PersonRegistry {   // agent -> World ID person; written only by REGISTRAR (the gateway)
    event AgentRegistered(address indexed agent, bytes32 indexed person);
    function personOf(address agent) external view returns (bytes32);   // 0 = not registered
    function register(address agent, bytes32 person) external;          // only REGISTRAR; idempotent; an agent never changes person
}
```
`TopicGraph.setRegistry(address)` wires it in; `Submissions` reads it through the graph.

### 3.3 Off-chain data formats (`shared/lore_shared/types.py`, as `TypedDict`s)

All JSON is stored on 0G Storage. Its on-chain hash is `keccak256` of the canonical JSON (keys sorted, no whitespace, UTF-8). Use one shared `canonical_hash()` helper.

```python
class InferenceReceipt(TypedDict):
    model: str; provider: str; chat_id: str
    trust_mode: Literal["private"]          # every Lore call is private
    tee_verified: bool                      # router's x_0g_trace.tee_verified
    signed_text: str; signature: str
    signer: str                             # recovered via EIP-191
    signer_matches_onchain: bool            # our own check against teeSignerAddress
    request_hash: str                       # keccak of the canonical request body (never the prompt itself)
    response_hash: str
    prompt_version: str; created_at: str

class VerifierReport(TypedDict):
    sub_id: str; topic_id: str; passed: bool
    checks: dict[str, bool]   # length, relevant, fits_topic, original_vs_graph, original_vs_pending, original_vs_public, ingested_by_gateway
    max_similarity: dict      # {node_id | sub_id, score}
    parents: list[dict]       # [{node_id, score}]
    reasons: list[str]        # short, human-readable; shown to voters
    receipts: list[str]       # 0G Storage roots of the InferenceReceipts behind this report
    created_at: str

class NodeMeta(TypedDict):  node_id: str; title: str; description: str; receipt: str; created_at: str
class TopicMeta(TypedDict): topic_id: str; title: str; description: str; node_count: int; receipt: str; created_at: str
```

**Content encryption (owned by P3, lives in `shared/lore_shared/crypto.py`):**
- Encryption is AES-256-GCM. Each node has its own key: `HKDF(MASTER_KEY, "lore-node:" + contentHash)`.
- The blob on 0G Storage is `iv || ciphertext || tag`.
- `MASTER_KEY` exists only in the gateway's secrets on our host. No other process holds it.
- `contentHash = keccak256(utf8(plaintext))`.

### 3.4 The hosted gateway: MCP, login and internal API

One service (`agents/gateway`). Users only ever reach it through MCP; Lore's own agents use the internal API.

| Path | Who | Does |
|---|---|---|
| `/mcp` | users (OAuth token) | The MCP server (streamable HTTP). Tools in section 3.5. |
| `/.well-known/oauth-*`, `/register`, `/authorize`, `/token`, `/revoke` | MCP clients | OAuth 2.1 (dynamic client registration, PKCE). `/authorize` sends the user to `/login`. |
| `/login?pending=…`, `/login/request`, `/login/complete` | the user's browser | World ID login. The proof's signal is the pending login's own id, so it can't be replayed into another login. Verified with World (`POST /api/v4/verify/{rp_id}`, allowed credentials only); the token's subject is the person. |
| `/internal/plaintext/{sub\|node}/{id}`, `/internal/candidates/{topicId}`, `/internal/topics/{topicId}` | verifier, curator | Unwatermarked plaintext and topic data. Requires `Authorization: Bearer {LORE_SERVICE_TOKEN}`. |

**"Open vote tasks"** means submissions in `Reported` status where any of the person's wallets is eligible (`canVote`), the window is still open, and the person hasn't voted.

### 3.5 MCP tools (hosted)

Every tool acts as the logged-in person, through the wallets linked to that person in `PersonRegistry`. When a person has several wallets, tools that need one take a `wallet` argument. Tools that change chain state sign with Turnkey, send, wait for the receipt and return the transaction hashes.

| Tool | Does |
|---|---|
| `lore_inbox` | Open vote tasks, plus what changed since the person last looked (their submissions' status, new nodes in their topics). |
| `lore_whoami` | The person and their linked wallets. |
| `lore_list_topics`, `lore_get_topic {topic_id}` | Public metadata, each title and description with its proof badge (model, provider, TEE verified, private). |
| `lore_my_vote_tasks`, `lore_get_vote_task {sub_id}` | The vote task with the verifier's verdict, reasons and proof badges; the text is watermarked to the voter. |
| `lore_create_wallet {email}`, `lore_wallet` | Create the person's Turnkey wallet (once) and link it on-chain; show wallets, whether Lore can sign for each, and their 0G and USDC balances. |
| `lore_vote {sub_id, approve}` | Sends `vote` from an eligible wallet. |
| `lore_submit {text, topic_id?, wallet?, confirm}` | Gates (World ID wallet, vote tasks, indexer lag, reserved characters), encrypts and stores the text, then sends USDC `approve` and `submit`. |
| `lore_buy {topic_id, wallet?, confirm}` | Sends USDC `approve` and `buy`. |
| `lore_read_topic {topic_id}` | Requires `hasAccess` on one of the person's wallets. Every node is watermarked to that wallet. |
| `lore_claimable`, `lore_claim` | Royalties owed; sends one `claim` per contributing wallet. |
| `lore_report_leak {topic_id, text, wallet?}` | Stores the evidence and sends `report`. |
| `lore_check_proof {root, claimed_output_json?}` | Re-checks a receipt against 0G's on-chain provider record (and optionally the output Lore claims it produced). |

Paying tools ask for `confirm=true` first, stating the amount, for example "This stakes 10 USDC".

---

## 4. Workstreams

Each workstream depends only on section 3. Use mocks for anything another workstream hasn't delivered yet.

### S — 0G Compute and Storage spike · owner: P3 (do this first, it blocks D's model calls and all storage)
Answer each question with evidence: a script in `spike/`, plus its output. Write the answers to `spike/FINDINGS.md`.
1. **Router from Python:** does the `openai` client with base URL `https://router-api.0g.ai/v1` work for a TeeML model, with `X-0G-Provider-Trust-Mode: private` and `verify_tee: true`? Show `x_0g_trace` and the `ZG-Res-Key` header.
2. **Signature check from Python:** fetch `/v1/proxy/signature/{chatID}`, recover the signer with `eth-account`, and read the provider's `teeSignerAddress` from the on-chain Service record. Which contract and method? Does it match?
3. **Retention:** how long does a provider keep the signature retrievable? This decides whether `lore_check_proof` must rely on the stored copy.
4. **Models:** which TeeML models are good enough for the verifier's checks and the curator's writing? Is there a TeeML embedding model?
5. **Storage from Python:** what is the supported route to upload and download on 0G Storage (an SDK, or the official CLI)? Measure upload and download latency.
6. **Attestation:** does `0g-compute-cli inference verify --provider` work on our host, and what does it output?

If 1 or 2 fails, **stop and escalate to the whole team**: the proof feature depends on them.

World ID questions (same spike, same evidence rules):
- **W1. Request signing and IDKit:** World ships `signRequest` (the `rp_context` signature) only for JS and Go. Port it to Python for the gateway, or run it as a tiny sidecar. Pin the `@worldcoin/idkit-core` ESM URL for `WORLD_IDKIT_MODULE` and confirm the page's `IDKit.request(...).preset(...)`, `connectorURI` and `pollUntilCompletion()` calls work.
- **W2. Device level:** the 4.0 docs only show the `orbLegacy` preset. Confirm how to accept device-level verification too (the decided policy is Orb or device).
- **W3. Signal and nullifier:** confirm how IDKit hashes a string signal into `signal_hash` (the gateway assumes keccak256(utf8) >> 8), and that one person's nullifier for Lore's action is the same whatever the signal (so all their agents map to one person). Also check whether it is the same across credential types (Orb vs device): if it differs, one human could register two agents as two people, so the gateway must accept only one credential type (`ALLOWED_CREDENTIALS` in `gateway/worldid.py`).
- **W4. Many agents per person:** configure Lore's action in the Developer Portal to allow unlimited verifications per person, and confirm a second agent's verification succeeds.
- **T1. Turnkey delegated access:** with Lore's Turnkey org, create one test wallet through `lore_create_wallet` and confirm: the activity versions and result fields in `gateway/turnkey.py` (`CREATE_SUB_ORGANIZATION_V7`, `CREATE_POLICY_V3`, `createSubOrganizationResultV7.wallet.addresses`); the policy syntax (lowercase addresses in `eth.tx.to`, `eth.tx.data[0..10]` and `[34..74]` slices) by checking that an allowed call signs and that a USDC `approve` to any other spender, a call to another contract, and another chain id are all denied; and a signed transaction on chain 16602 is accepted by the RPC. **Done 2026-11-07** (`spike/turnkey_t1.py`): every check passed; see `spike/FINDINGS.md`. Still open: the user signing in to Turnkey with their email to revoke Lore.

### A — Contracts (`contracts/`) · owner: P2
1. `MockUSDC`, `LoreRoles`, `Constants.sol`.
2. `TopicGraph`, `Submissions`, `Access`, `Royalties` and `Reports`, implemented exactly as specified in section 3.2.
3. Foundry tests. At minimum:
   - New-topic accept and reject.
   - Existing-topic outcomes: quorum yes, quorum no, a tie, and no quorum (verifier decides).
   - Early finalize once the outcome can't change.
   - Every voting eligibility rule, each tested on its own.
   - A rejected stake goes entirely to treasury, and voters' balances don't change.
   - Royalties: a node accepted after a sale earns nothing from that sale; dust goes to treasury.
   - Soulbound transfers revert; a second `buy` reverts.
   - Invalid parents revert: wrong topic, missing, duplicate, too many.
4. One fuzz test showing that, across any sequence of sales and claims, the total paid out never exceeds the total received.
5. `script/Deploy.s.sol`: deploy everything, wire the roles, write the addresses to `shared/lore_shared/deployments/<chainId>.json`, and export ABIs to `shared/lore_shared/abi/`.

**Done when** `forge test` passes and the contracts are deployed to the 0G testnet with addresses committed.

### B — Hosted gateway and MCP server · owner: P1
1. **Indexer** (in the gateway): with `web3.py`, backfill with `get_logs` from the deploy block, then poll new blocks for every event in section 3.2 and write them to SQLite tables `topics`, `nodes`, `edges`, `submissions`, `votes`, `purchases`, `reports`, `ingests`, `persons`. Handling the same event twice must not change anything.
2. **Finalizer:** every minute, call `finalize` on each submission that is eligible (window over, or the outcome can't change). The gateway's own wallet pays the gas.
3. **Metadata cache:** on `NodeMetaSet` and `TopicMetaSet`, fetch the JSON from 0G Storage, check it against the on-chain hash, and cache it.
4. **MCP server and login** exactly as in sections 3.4 and 3.5: OAuth 2.1 with World ID as the only login, every tool acting as the token's person, and the vote-before-submit gate per person.
5. **Internal API** for the verifier and curator, authenticated with the shared service secret.

**Done when** an MCP client connected to the hosted server, logged in with World ID, can create and fund a Turnkey wallet and run the full loop (buy, read, submit, vote, claim, report) against the deployed contracts (with C and D mocked as needed).

### C — Content: crypto, watermarking, leak tracing, storage · libraries: P3, wiring into the gateway: P1
1. **(P3)** `crypto.py`: `encrypt_node`, `decrypt_node`, `content_hash`. Include a round-trip test.
2. **(P3)** `watermark.py`, watermark v1. It is deterministic, so no per-delivery seed needs to be stored.
   - The only marking is zero-width characters. The first 8 bytes of `HMAC(WM_SECRET, wallet || ref)` are encoded as zero-width characters and repeated after every sentence end, so a partial excerpt can still be matched. The visible text is unchanged.
   - `ref` is `node:<nodeId>` for a buyer's node copy or `sub:<subId>` for a voter's submission copy. IDs are canonical positive decimal uint256 values (no leading zeroes). The HMAC input is the wallet's 20 raw bytes followed by the UTF-8 ref; `node:5` and `sub:5` must produce different marks even for the same wallet and text.
   - `watermark(text, wallet, ref)` and `score(leaked_text, wallet, ref) → 0..10000`, where the score is the fraction of decoded bits that match. HMAC truncation, zero-width bit encoding and framing stay unchanged.
   - Also mark nonempty prose line endings so Markdown bullet excerpts are covered, and recognize Chinese sentence punctuation without following spaces. Leave Markdown inline code and fenced code untouched; code-only excerpts are not traceable by this scheme.
   - `validate_plaintext(text)` rejects reserved watermark characters (U+200B, U+200C, U+2063) and text that cannot encode as UTF-8. `watermark` calls it too. Reject rather than stripping characters from hashed research or stacking old marks.
   - Tests:
     - Two different wallets produce different output.
     - The same wallet always produces the same output.
     - The visible text is identical to the input.
     - A 3-sentence excerpt still scores highest for the correct wallet.
     - The same wallet and text have different output for `sub:5` and `node:5`.
     - A 3-sentence vote-task excerpt is traced to the correct `(wallet, sub:<id>)` among at least 50 decoy wallets with mixed buyer/node and voter/submission refs.
     - Markdown bullets and Chinese prose remain traceable; inline/fenced code is preserved; already-marked text and lone surrogates are rejected.
   - Known limitation: stripping zero-width characters removes the mark. That is accepted for v1; stronger watermarks are v2.
3. **(P3)** `leak.py`: `best_match(text, candidates)` takes `(wallet, ref)` pairs and returns `(wallet, ref, score_bps)` for the highest-scoring delivery using `score()`, **only among candidates with at least one exact complete HMAC mark in the excerpt**. With no exact candidate mark, return `(None, None, 0)`; similarity alone must never name a wallet. Scores still measure all decoded bits, allowing mixed-node excerpts without an arbitrary score threshold. Equal scores break lexicographically by `(normalized_wallet, ref)`; a score or tie is not proof of attribution. Test at least 50 decoy wallets, 1,000 fabricated marks, an out-of-candidate real mark and mixed-node leaks.
4. **(P3)** `storage.py`: `upload(bytes) → root` and `download(root) → bytes`, using the route spike S picked.
5. **(P1)** The gateway's content paths: `lore_submit` (ingest), `lore_read_topic`, `lore_get_vote_task`, `/internal/*`, and the leak lookup.
   - Every call checks access, eligibility or role on-chain at request time. Do not cache those checks.
   - `lore_submit` calls `validate_plaintext` before encrypting/uploading and refuses invalid input with a clear error. The library's delivery-time validation is a second guard, not a replacement for ingest validation.
   - `lore_read_topic` watermarks each node with `node:<id>` after the access check. `lore_get_vote_task` watermarks only `text` with `sub:<subId>` after the eligibility check; `report`, `receipts` and `parents_meta` are unchanged. `/internal/*` stays unwatermarked and role-protected.
   - The leak lookup runs when `LeakReported` is indexed. It uses every logged `(wallet, ref)` for that topic, including voters who never bought it, calls `best_match`, then calls `recordMatch(reportId, wallet, score_bps)`. The matched ref remains off-chain; no contract or section 3 API change is needed.
   - Handle `(None, None, 0)` explicitly as unmatched; never substitute a wallet or pass `None` into a contract call. P1/P2 must agree whether an unmatched report stays pending or uses an existing supported zero-address sentinel.
   - Tests: vote-task copies differ by wallet but preserve visible text; ineligible wallets are still refused; a voter fetches a task, the submission is accepted, and a later 3-sentence leak matches the voter even with buyer copies present. Also retain tracing for rejected submissions.
6. **(P1)** Record every user plaintext delivery as `(wallet, topic_id, ref)`: one row per node returned by `lore_read_topic`, or one submission row from `lore_get_vote_task`. Duplicate rows are idempotent. Keep submission delivery refs after acceptance or rejection; do not rewrite them as node refs. This delivery log is the candidate set for the leak lookup.

**Done when** these paths pass integration tests against the testnet contracts and a planted leak is traced back to the correct wallet.

### D — Verifier and curator agents · owner: P1

**`agents/zg/`:** the only model client. It implements section 2.1 fully: `call()`, `embed()` (if spike S found a TeeML embedding model), receipt building, signature verification and the receipt upload. Tests:
- A private call with no TeeML provider available raises an error; it never downgrades.
- `tee_verified: false` raises an error.
- A tampered signature, or tampered text, fails verification.
- No code path can send a request without the private header.

**Verifier, which runs on every `Submitted` event it sees on-chain:**
1. Check that `contentHash` was ingested through the gateway (the `ingests` table). If not, fail the submission: it skipped the vote gate, or the gateway can't decrypt it.
2. Load the submission through `/internal/plaintext`, and the topic's accepted nodes and earlier pending submissions through `/internal/candidates`.
3. **Length:** must be between `MIN_CHARS` and `MAX_CHARS`.
4. **Similarity:** embed the text. Find its maximum cosine similarity against the topic's accepted nodes, and against **pending submissions with a smaller subId** in the same topic. If either is ≥ `DUP_SIMILARITY`, fail. (This is the "earlier one wins" rule.)
5. **LLM checks:** one `zg.call()` with a fixed, versioned prompt returns JSON `{relevant, fits_topic, original_vs_public, reasons[]}`.
   - It receives the topic metadata and the titles of the closest nodes.
   - For a new topic, `fits_topic` means "is this a coherent standalone topic".
   - How `original_vs_public` checks public sources is an open item (section 7). Never send the submission text to anything outside 0G private mode.
6. **Edges:** `hybrid = 0.7 × cosine + 0.3 × BM25` (BM25 normalised to 0..1) against the topic's accepted nodes. Suggest the top `MAX_PARENTS` nodes scoring ≥ `EDGE_SIMILARITY`. An empty list is allowed: the node becomes a new top-level node.
7. Build the `VerifierReport` with its `receipts`, upload it to 0G Storage, then call `postReport(subId, passed, parents, canonical_hash(report))`.

**Curator, which runs on every `NodeAdded` event it sees on-chain:**
1. Get the plaintext through `/internal/plaintext`, then write `NodeMeta` with one `zg.call()`: a title of at most 80 chars and a description of 300–600 chars. The description must say what the node contains well enough for a buyer to decide, without giving away the content itself.
2. Rewrite `TopicMeta` with one `zg.call()`, using the existing topic metadata plus every node's metadata (not the full texts).
3. Attach each call's receipt, upload both to 0G Storage, then call `setNodeMeta` and `setTopicMeta`.

Both agents keep their prompts in versioned files (`prompts/v1.md`) and record the prompt version in every receipt. They sign on-chain with the `VERIFIER` and `CURATOR` role wallets, whose keys are held in our host's secrets.

**Done when:**
- These four fixture cases behave correctly against testnet:
  - An exact duplicate is rejected.
  - A near-duplicate of a pending submission is rejected.
  - An off-topic text is rejected.
  - A valid follow-up gets the correct parent.
- Every report and every piece of metadata carries receipts that pass `lore_check_proof`.

### F — Hosting our agents · owner: P3
1. Choose the host and write `deploy/` so the gateway, verifier and curator each run as one service. Use plain `docker compose` unless the host needs something else.
2. Generate the role wallets, store every secret in the host's secret store, and have P2 grant the on-chain roles. Create the 0G Router API key with `trust_mode: "private"`.
3. Run the daily provider attestation job (section 2.1, item 6).
4. Write a short runbook in `deploy/RUNBOOK.md` covering redeploying, rotating secrets and reading logs.
5. Give each Lore agent role its own key: gateway (`LEAK_DETECTOR`, `REGISTRAR`), verifier (`VERIFIER`), curator (`CURATOR`). Separate processes sending from one key can pick the same nonce; the deploy script's default of one deployer key for every role is for local development only.
6. A new contract deployment means fresh gateway and job databases. They record the deployment they were built for and refuse to start against another one; delete them and let them re-index.

### E — Integration and end-to-end (`e2e/`) · owner: P3
`e2e/run.py` drives four test agents (four people), each using only the hosted MCP server: it logs in, creates a Turnkey wallet with `lore_create_wallet`, gets it funded with MockUSDC and 0G, and lets Lore sign every transaction. It asserts the results.
1. Agent 1 creates a new topic, which the verifier accepts. Agent 1 is now a contributor.
2. Agent 2 buys the topic and reads it. Agent 1 claims royalties.
3. Agent 2 submits a follow-up. The submission is gated until Agent 2 has no vote tasks, which it doesn't.
4. Agent 1 is forced to vote before its own next submission. It votes yes, the follow-up is accepted, and the edge points to node 1.
5. Agent 3 submits a near-copy of a pending submission. It is rejected and its whole stake goes to the treasury.
6. Agent 3 buys the topic, then "leaks" a 3-sentence excerpt of its copy. The leak lookup matches Agent 3's wallet.
7. Every receipt produced during the run passes `lore_check_proof`, and a tampered one fails.
8. The script asserts every balance, every status, and the final graph shape.

---

## 5. Milestones and dependencies

| Milestone | P1 (agents) | P2 (contracts) | P3 (platform) | Depends on |
|---|---|---|---|---|
| **M0** | Reviews section 3 | Network config; reviews section 3 | Spike S answered; `shared` scaffolded | — |
| **M1** | — | A: contracts tested and deployed to testnet | — | M0 |
| **M2** (parallel with M1, on local anvil) | B hosted gateway and MCP server; `zg` client; D verifier and curator with fixtures; content endpoints wired | Supports P1 and P3 against anvil | C libraries (crypto, watermark, leak, storage) tested | M0 |
| **M3** | Fixes deployment issues | Grants roles on testnet | F: our three agents hosted and pointed at testnet | M1, M2 |
| **M4** | Fixes bugs found | Fixes bugs found | E: `e2e/run.py` passes on testnet twice in a row from a fresh deploy | M3 |

Until M1 lands, P1 and P3 develop locally against an anvil chain using `forge script Deploy`.

---

## 6. Conventions
- Conventional Commits. One unit of work per commit.
- Secrets (`MASTER_KEY`, `WM_SECRET`, role wallet keys, the 0G Router API key) go only in the host's secret store, or a local `.env` during development. Never commit them or log them. Users' keys never leave their machines.
- No endpoint returns plaintext unless the access, vote-eligibility or role check has passed. **This is the core security property of v1. Every endpoint that returns content needs a test asserting the check is there.**
- Submission and node text never goes to any model or service outside 0G private mode.
- Keep it lean. Don't add a framework, abstraction or service that this plan doesn't call for. If you think something is missing, raise it with the other two instead of building it.

## 7. Open items (decide before M3; placeholders are fine until then)
- Final economic values in section 3.1.
- How the verifier checks originality against public sources without leaking the submission. One option: a private `zg.call()` extracts short search queries, and only those queries go to a search API.
- ~~Which host runs our three agents (P3).~~ Decided: one Azure VM (`deploy/azure.sh`, `deploy/RUNBOOK.md`).
- Whether the finalizer's gas comes from the treasury or the gateway's own wallet.
- Royalty dilution (deferred): every accepted node shrinks existing contributors' royalty share, so contributors still have a reason to vote no on good work. Decide how to counter it, for example weighting royalties or rewarding contributors for growth of their topic.
