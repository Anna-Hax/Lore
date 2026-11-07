# Proposal: topics priced by their authors' comfy tokens

Status: **built and deployed on Galileo (2026-11-07)**; `BUILD_PLAN.md` section 3 now describes it. Not yet on 0G mainnet.

**What changed from this proposal while building it:** there is no price oracle. comfy's router buys an exact amount and refunds what it didn't need, so `Access.buy` pays each author's tokens at the live market price out of the buyer's own `msg.value` (their maximum). The gateway only quotes, by simulating each purchase on the router. That removed the `PRICE_ORACLE` role and its trust assumption.

**Evidence:** 90 Foundry tests; `ComfyFork.t.sol` buys real comfy tokens on a 0G mainnet fork; the Galileo e2e run passed (stakes in 0G, a purchase that locked three authors' tokens for the buyer, the leak trace and a royalty claim); spike T1 `--quick` confirmed the Turnkey value cap.

The original proposal follows. It changes `BUILD_PLAN.md` section 3, the frozen interfaces, and replaces the unintegrated dynamic-pricing model in `shared/PRICING.md`.

## 1. The model

- **Every author has a comfy token.** An agent can't submit until its wallet is linked to a comfy token it launched. There is no tokenless fallback.
- **The topic price is a base price plus a basket of author tokens**, in native 0G:

  ```
  price(topic) = basePrice + tokensPerNode × Σ_authors nodes(author) × twap(author's token)
  ```

  `twap` is a time-averaged price, not the spot price, so a buyer can't dump a token just before buying.
- **The buyer pays in 0G.** No USDC, no MockUSDC.
- **The base price is the real access price.** It's paid as royalties in 0G to the topic's contributors, through the existing royalty weights.
- **With the token part, the contract buys each author's tokens on comfy, in the same transaction.** The tokens go into a lock vault in the buyer's name, claimable after `lockPeriod` (proposed 30 days). Only then can the buyer sell them.
- **The buyer gets permanent access**, including future nodes. Future authors earn from future buyers' base royalties and token purchases.
- **Each comfy buy pays its own trading charges.** That's comfy's base fee and the author's creator tax, and the compute share of those feeds the author agent's 0G compute account. That's the "pays for itself" loop for authors.

Why the base price and the lockup: without them, a buyer could buy the topic and immediately sell the tokens back, so access would be nearly free and authors would earn almost nothing.

## 2. Facts this depends on (comfy docs, checked 2026-11-07)

| Fact | Source |
|---|---|
| comfy runs on **0G mainnet, chain 16661**, and trades use real 0G | [docs](https://www.comfy.fun/docs) |
| Tokens are **ERC-20**: "no mint · no transfer tax". Each pairs with **native 0G**, and liquidity is "locked · no removal" | [integrate](https://www.comfy.fun/docs/build/integrate) |
| There is no bonding curve. Pools live in a singleton `CLPoolManager` `0xAabD…08b0`, which looks Uniswap-v4-like (an inference) | integrate |
| The launcher is `AgentLauncher` `0x2F74…E86a`. `isComfyToken(token)` exists, and the `Launched(poolId, token, creator, …)` event names the creator | integrate |
| Buy and sell charges: base fee, opening fee and an optional creator tax. A share of creator fees goes to the creator's 0G compute account and can't be withdrawn | [fees](https://www.comfy.fun/docs/trading/fees) |
| **Router:** `ComfyRouter` `0x7652…8d9e`, source verified on chainscan, used by comfy's own UI (3,359 trades). `buyExactWithNative(PoolKey, amountOut, recipient, deadline)` is payable, buys an exact number of tokens, sends them to `recipient` and refunds unused 0G to the caller with a full-gas `call`. It has no owner, pause or upgrade | spike C1 |
| **Price:** `CLPoolManager.getSlot0(poolId)` gives `sqrtPriceX96`, and the price in 0G per token is `2^192 / sqrtPriceX96²`, since native 0G is `currency0`. `poolIdToPoolKey(poolId)` gives the swap key. There is no on-chain average | spike C1 |
| **A simulated buy works:** 1,000 tokens of a live token cost 0.064849 0G against a spot of 0.064200, i.e. comfy's 1% base fee, for about 204k gas per author | `spike/comfy_c1.py` |

## 3. Decisions (agreed 2026-11-07)

**Spike C1 passed, read-only (`spike/comfy_c1.py`).** A contract can buy comfy author tokens atomically, and the gateway can read their prices. Still open: a real transaction from a contract, which the Phase 2 mainnet fork test covers. `Access` needs a `receive()` for the router's refund, plus a reentrancy guard, because the refund calls back into it.


1. **Lore moves to 0G mainnet (16661), with real 0G, and a mirrored testnet stays for tests.** comfy exists only on mainnet. So Galileo runs the same Lore contracts against a `MockComfy`: one small contract with the same `buyExactWithNative`, `getSlot0` and `poolIdToPoolKey` signatures, a settable price, and a token it mints. All e2e and day-to-day tests run there for free. Mainnet gets only the fork test and a minimal smoke run, not extensive tests. Buying comfy tokens has to happen on comfy's chain, inside the purchase transaction.
   - All Lore contracts are redeployed there.
   - Stakes and fees are in 0G too, and USDC is removed entirely.
   - 0G Storage moves to mainnet as well.
   - Every action costs real 0G, so the team has to budget for it.
2. **Price source.** comfy's pools expose no time-averaged price.
   - **Agreed:** a `PRICE_ORACLE` role (the gateway) posts each author token's time-averaged price every few minutes. It averages `getSlot0` samples, which C1 confirmed the gateway can read. `Access` refuses prices that are stale, or that moved more than a bound since the last post.
   - This is a new trust assumption, the same kind as the REGISTRAR role.
3. **Identity.** A token belongs to an **agent wallet**. People may launch on comfy from any wallet, for example MetaMask, so linking proves control.
   - The creator wallet signs a Lore message naming the agent wallet and the token.
   - The gateway checks `isComfyToken(token)`, that the creator in `Launched` matches the signer, and the signature.
   - The gateway, as REGISTRAR, then writes `tokenOf(agent) = token` on-chain.
4. **Turnkey policies widen**, which needs team agreement:
   - chain 16661;
   - `Access.buy` with a non-zero value, capped per transaction;
   - `LockVault.claim`, with the recipient pinned to the wallet itself.

   Selling claimed tokens happens on comfy and is out of Lore's scope. The user signs that in Turnkey, or moves the tokens to their own wallet first.
5. **Bounds (agreed for the hackathon):** `maxAuthorsPerPurchase`. Each author is one swap, so gas grows with the number of authors. Topics over the bound have their smallest holdings rounded into the base price.

## 4. Work, by owner

### Phase 0: spike C1 (P1), done 2026-11-07, see section 2
- Find comfy's router from the `ChargeTaken.router` addresses in mainnet logs, then read its verified source on chainscan.
- Write a mainnet test contract that buys one comfy token for 0G in one transaction, with a minimum output, and reports the actual charges and gas.
- Derive the price from `Swap.sqrtPriceX96` and check it against comfy's UI.
- **Stop and rethink if a contract can't buy comfy tokens atomically.**

### Phase 1: frozen interfaces (P1, P2 and P3 together)

`BUILD_PLAN.md` section 3:
- **§3.1:** `BASE_PRICE`, `TOKENS_PER_NODE`, `LOCK_PERIOD`, `MAX_AUTHORS`, `PRICE_MAX_AGE`, `PRICE_MAX_MOVE_BPS`, and stake and fee amounts in 0G.
- **§3.2:** the contracts listed in Phase 2.
- **§3.3:** node metadata gets `author` (agent wallet) and `author_token`.
- **§3.5:** `lore_link_token`, plus the new `lore_buy` and `lore_claim_tokens`.

### Phase 2: contracts (P2)
- **`AgentTokens`:** `tokenOf(agent)`, set by REGISTRAR, and `Linked` events.
- **`PriceOracle`:** `PRICE_ORACLE` posts `(token, priceX96, updatedAt)`.
- **`Submissions`:** `submit` reverts without `tokenOf(msg.sender)`. Stake and fee in native 0G.
- **`Access.buy(topicId, maxPrice)` (payable):**
  1. compute the price from the oracle;
  2. send the base price to `Royalties`;
  3. swap 0G for each author's token, with a minimum output from the oracle price and a tolerance;
  4. deposit the tokens in `LockVault` for the buyer;
  5. refund the unspent 0G;
  6. grant access.

  It's atomic: any failure reverts everything.
- **`LockVault`:** `claim(token)` after `unlockAt`, only to the buyer.
- **`Royalties`** in native 0G.
- **Foundry tests,** including a **mainnet fork test** against a real comfy pool, plus price manipulation, stale price, refund, the authors bound and lock timing.

### Phase 3: gateway, MCP and agents (P1)
- **`lore_link_token(token, signature)`:** the checks from §3.3 above, then the REGISTRAR transaction.
- **`lore_submit`** refuses, with instructions, when the agent has no linked token.
- **`lore_buy`** quotes a breakdown: base, each author's tokens and price, the lock date, and the maximum price.
- **`lore_claim_tokens`.**
- **A price keeper loop** in the gateway worker: time-averaged prices from `Swap` logs, posted to `PriceOracle`.
- **Curator:** writes `author` and `author_token` into node metadata.
- **Explorer:** shows each node's author token, with a link to its comfy page.
- **Turnkey:** the new policy set, re-run through spike T1 on chain 16661.

### Phase 4: platform (P3)
- `network.py` entries for 16661, verified against the official 0G docs (RPC, explorer, storage endpoints).
- The mainnet deploy, with a funded budget.
- 0G Storage on mainnet.
- RUNBOOK updates.
- **e2e:**
  - each test author launches a comfy token once, by hand. That costs real 0G, and comfy needs the browser flow;
  - the run links them;
  - the full buy flow asserts the base royalties, the vault balances, the lock and the refund.

### Phase 5: track evidence ("Agents that pay for themselves")
- Authors launch with the compute share on. Show a buy's comfy charge reaching an author's compute account, then inference paid from it with a capped key: transaction hashes plus Router request ids.
- Lore's own verifier and curator: fund their compute from the treasury's 0G (platform cut and rejected stakes) automatically. A separate item: whether Router accounts can be topped up programmatically is still unverified.

## 5. Risks and open questions

- **Real money:** every test, demo and user action costs mainnet 0G, and the e2e needs real comfy launches.
- **Onboarding friction:** a comfy launch needs a human in a browser. It can't be done inside MCP onboarding.
- **Oracle trust:** a compromised gateway could post bad prices, bounded by the move limit and the buyer's `maxPrice`.
- **Thin pools:** price impact on small authors' tokens. `maxPrice` protects the buyer, but purchases can fail.
- **An author abandons their token,** so its price decays. That's acceptable: the basket reflects the market.
- **comfy changes:** comfy can change where an unlocked compute share goes, and its router isn't a documented API, so it could change.
- **`shared/PRICING.md`** (the unintegrated dynamic-pricing model) is dropped by decision. Voters stay unpaid.
