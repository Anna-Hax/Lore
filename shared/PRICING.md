# Dynamic pricing: P3 implementation and integration handoff

Based on the supplied `context.md`, after fetching and merging `origin/main`
at `698649b`. The user selected the attachment's voter rewards, replacing main's
treasury-only slash policy **for this new model**. Edits stay within P3's paths.

The implementation is an executable reference and shared arithmetic library.
The deployed contracts and P1 gateway still use the fixed-price interfaces.
This work does not make the live platform charge dynamic prices. P1/P2 must
integrate it, update the frozen plan interfaces together, export new ABIs and
deploy the replacement contracts before enabling it.

## What is implemented

| Location | Behavior |
|---|---|
| `lore_shared/constants.py:PricingParameters` | Validated, immutable dynamic parameters; complete snapshot comparison rejects missing, mistyped or drifted live values |
| `lore_shared/pricing.py` | Integer price formula, bounded demand buckets, fee/stake snapshots, component scores, QF, base weights and capped direct-parent bonuses |
| `lore_shared/economics.py` | Vote resolution, voter fee/slash allocations, scaled royalty accounting and forfeiture redistribution |
| `lore_shared/types.py` | Explicit new report/metadata shapes with integer bps and advisory `suggested_p0` |
| `lore_shared/leak.py:match_evidence` | Exact-mark attribution with cross-wallet ties exposed; original `best_match` tuple stays compatible |
| `../e2e/pricing_reference.py` | Offline topic state model: initial-price lock, purchases/access, acceptance-time weights, claims, payee recovery and reviewed revocation |
| `../e2e/test_pricing_model.py` | Document walkthrough, failure cases, accounting counterexample and randomized conservation checks |

`Constants`, existing report types and module-level economic defaults remain
compatible with the current deployment. New integrations must explicitly use
`PricingParameters`, `PricingVerifierReport` and `PricingTopicMeta`. Old stored
float scores must never be reinterpreted as integer bps. P1 should select the
record format by deployment/version when migrating the metadata cache.

## Pricing and submission amounts

All amounts are integer USDC micro-units. At defaults:

```python
from lore_shared.constants import PricingParameters
from lore_shared.pricing import DemandWindow, submission_cost, topic_price

params = PricingParameters()
# Startup: assemble values from P2's getters at one block, using these names.
# params.assert_matches(live_parameter_snapshot)

price = topic_price(5_000_000, nodes=3, buyers30d=2, params=params)
assert price == 6_840_000
cost = submission_cost(price, params=params)
assert (cost.fee, cost.stake, cost.total) == (1_000_000, 2_000_000, 3_000_000)
assert submission_cost(params=params).total == 3_000_000  # new topic
```

The calculation retains all four square-root decimals through multiplication:
`p0 * (10000 + nodeStep*(nodes-1)) * (10**8 + demandStep*isqrt(buyers*10**8)) // 10**12`.
Apply the `20*p0` cap, then floor to the price tick. Do not round the demand factor
to whole bps first. Python intermediates are unbounded; Solidity must use safe
full-precision multiplication/division and cap before overflowing large factors.

The window uses six epoch-tagged buckets, with five-day epochs. Views ignore
expired buckets without writing. Every successful purchase is quoted **before**
counting that purchase. Existing contributors' purchases are excluded. After six
epoch transitions an old bucket is ignored, even if nobody bought in between.

P0 is set once by the root contributor before the first sale, within $1–$50,
otherwise $5. Access is permanent; contributing grants no access. A contributor
must buy before submitting to an existing topic. Reject repeat/revoked purchases.
Slippage failure must leave USDC, access, royalties and demand unchanged. Pull
exactly `priceOf(topicId)` after checking `maxPrice`; approval may cover `maxPrice`.

The fee is always retained separately from stake. Acceptance refunds all stake.
By default, acceptance sends the $1 fee to treasury; a configurable fee share can
pay winning voters. On rejection that agrees with the verifier, 50% of stake is
split among winning no voters. An overturned verifier pass sends all stake to
treasury. No winners means all stake/fee goes to treasury. Per-voter allocations
round down; residual whole micro-units go to treasury. Rewards must be claimed
once per voting **person**, preserving main's World ID rules. Snapshot amounts
and relevant rates so a later admin change cannot alter a pending obligation.

`BUY_REBATE` remains disabled. The attachment gives no amount/eligibility formula
for enabling it; do not promise or mint rebates without a funded policy.

## Quality and voting details requiring care in P1/P2

- All new similarity and quality fields use integer bps. Normalize embedding
  scores into that domain before building the new report. Score weights are
  novelty 40%, correctness 35%, usefulness 25%; similarity <=5000 gives full
  novelty and >=9200 gives zero novelty.
- Use private verified `agents/zg` receipts for model assessments. P3 adds no
  model client. `quality_scores` computes raw scores, not permission to accept.
- **The attachment has an acceptance inconsistency.** A duplicate at similarity
  9200 with perfect correctness/usefulness has weighted score 6000, yet must be
  rejected. The proposed `pass == (score >= 5000)` rejects that valid rejection.
  Other mandatory checks can fail with high quality too. P1/P2 must represent
  hard-check failures in the report/contract decision, or explicitly define an
  effective-score policy. Do not silently falsify raw subscores to make the
  equality pass. The raw-score regression preserves this counterexample.
- `vote_outcome` implements the attachment literally: one side **strictly
  exceeds** `eligible * QUORUM_BPS / 10000`. Main instead checks total votes
  `>=` quorum. These differ; this is a deliberate migration, despite the
  attachment describing quorum as “unchanged.” Keep World ID eligibility and
  one-person voting; the economic change does not remove them.
- `OVERTURN_BPS=6667` is a literal integer threshold: two of three dissenters
  (6666.66 bps) do **not** overturn; three of four do. Use cross multiplication.
- Approval is floored to integer bps, then the combined score is floored to bps,
  then QF is computed. Root QF is capped at 12000. A rejected node gets no weight.
- **Old early-finalization logic cannot be reused.** Three yes votes out of five
  fix an accepting verdict, but two subsequent no votes change QF from 13000 to
  9000 for verifier score 8000. A conservative implementation waits for the
  deadline or every actually eligible person to vote. The snapshot count must
  account for the excluded submitter and strict pre-report contribution time.

## Royalties: necessary correction to the attachment

The proposed per-sale dust rule is insolvent. With one node of weight 30000,
two $5 purchases and a 20% cut:

- Each sale computes `dust = 1` micro-unit and credits it to treasury.
- After both sales, the cumulative accumulator makes 7,999,999 micro-units
  claimable by the node.
- Treasury holds 2,000,002. Total obligations are 10,000,001 against 10,000,000
  received. `test_proposal_dust_rule_can_double_allocate_sale_revenue` reproduces it.

Also, rounding debt to whole micro-units when assigning weight gives a new node
part of an old fractional entitlement. The shared arithmetic corrects both:

1. Keep **credit and debt scaled by 1e18**. Settle old weight exactly in scaled
   units before reweighting; new debt is `new_weight * acc`, with no early floor.
2. Claims pay `credit_scaled // 1e18` and retain the fractional remainder.
3. Sales credit only the platform cut to treasury. The undistributed scaled
   remainder stays reserved in the contract. Do not sweep it to treasury or
   recycle it into a later contributor cohort.
4. With zero weight, the whole sale goes to treasury. Every payout remains a
   pull operation; sales must not transfer to a contributor or treasury address.
5. On revocation, remove **all** affected weights before redistributing their
   scaled forfeited earnings. With no remaining weight, transfer whole units
   to treasury and reserve the fraction. Parent bonuses previously awarded stay.

The reference checks exact conservation in scaled units:

```
received * 1e18
  == (claimed + treasury_withdrawn + treasury_accrued) * 1e18
     + sum(node_accrued_scaled) + reserved_scaled
```

This is an explicit correction to the attachment, not a claim that its original
rounding was safe. P2 should port these vectors to Foundry invariants. The Python
state model is an oracle; it is not production persistence or contract code.

## Recovery and leak revocation

The reference models a recovery address set in advance by the contributor,
a request by that recovery address, a seven-day wait and completion. The current
payee may cancel during the wait. Configuring another recovery address clears
an outstanding request. Recovery changes payee only; it never moves access.
P2 must specify these request/complete/cancel entry points and their events.

`match_evidence` returns the deterministic winner plus all distinct wallets tied
at its score. Multiple refs for one wallet are not a cross-wallet tie. P1 must
persist this evidence; `best_match` alone loses that information. Neither result
is proof that a person leaked, and neither triggers an automatic penalty.

Revocation requires an ADMIN decision, a report for that same topic and wallet,
score >=9000, no cross-wallet tie, and 72 hours since **match recording**. The
current Reports ABI records neither match time nor tie status; P2 needs both.
Revocation burns access, blocks buying again, zeros every affected node's weight
and forfeits unclaimed earnings, including earnings whose payee was recovered.

**Bounded execution remains a P2 design requirement.** A wallet can own an
unbounded number of nodes. The offline model loops over them solely to define
final balances. Do not copy that loop into `revoke` on-chain. A bounded batch or
aggregate accounting design must freeze affected claims, exclude all affected
weights from redistributed funds and handle concurrent sales/acceptances without
partial-revocation gains. The attachment does not specify that protocol.

## Integration checklist

P2: dynamic `Access.priceOf`, `buy(topic,maxPrice)`, initial-price setter and
demand buckets; separate fee/stake escrow and existing-topic access gate;
scored `postReport`, corrected finalization and QF; weighted royalties and pull
treasury; voter reward claims; recovery; match-time/tie evidence and bounded
revocation. Export changed ABIs/deployments and mirror dynamic parameters.

P1: read live parameters at one block and reject configuration drift; show live
quotes and include `maxPrice` in prepared transactions; approve fee+stake; use new
report/metadata formats and receipts; prepare voter reward claims; persist match
ambiguity/time; expose recovery and revocation only through appropriate paths.
Preserve World ID, vote gating and all plaintext authorization checks.

P3: the offline tests below are ready. Adapt the hosted-MCP scenario after P1
transaction signing and P2 contracts land. The existing `e2e/run.py` remains
paused on main; no live dynamic-pricing test or deployment has been claimed.

```sh
shared/.venv/bin/python -m pytest shared/tests/test_pricing.py \
  shared/tests/test_economics.py shared/tests/test_leak_evidence.py \
  e2e/test_pricing_model.py -q
```

Validation in this checkout: 76 pricing/economics/leak-evidence tests passed;
the wider P3 suite passed 188 tests (including those 76). The five gateway
integration tests passed separately using the locked agent dependencies in a
temporary environment: **193 passing tests total**. The full `agents/tests`
run stopped making progress after 37 tests and was interrupted; it is not
reported as passed. No testnet calls, paid model calls or deployments were run.

Plan changes to make in the coordinated integration PR: replace fixed-price
and equal-split product rules; specify the formula, voter rewards and explicit
quorum change; update sections 3.1–3.3 for parameters, methods and data formats;
describe the royalty correction and report-hard-failure decision; update A/B/D/E
acceptance tests. A demand formula with no reserve or resale is not a bonding
curve. These frozen-interface edits have not been made from P3's paths.
