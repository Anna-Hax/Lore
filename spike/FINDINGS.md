# P3 spike findings

Last updated 2026-11-06 (evening). **All six S questions are answered live** (see "Live results" below).
S2 and S4 were first answered from public reads; S1, S3, S5 and S6 ran against the real Router,
0G Storage and providers with a private-mode Router key and a funded testnet wallet.

## Live results (2026-11-06)

| S item | Result |
|---|---|
| 1. Router from Python | **Works.** Private mode (`X-0G-Provider-Trust-Mode: private`, `verify_tee: true`) returns 200 in ~2 s. `ZG-Res-Key` is a response header. The provider was a **mainnet (16661)** service, confirming the catalogue match. `x_0g_trace` holds only `billing`, `provider`, `request_id`: **there is no `tee_verified` field**, so `zg` treats only an explicit `false` as a failure and relies on its own signer check. `glm-5.3` reasons before answering: tiny `max_tokens` returns empty content. |
| 2. Signature + signer | **Works, with an E2EE caveat.** `GET {provider}/v1/proxy/signature/{chatID}?model=` returns `{text, signature, signing_address, signing_algo}`; the recovered signer equals the provider's on-chain `teeSignerAddress`. The Router always seals private requests (`x-0g-e2ee: sealed`; an `X-0G-E2EE` header does not change it), so `text` is `zg-sig-v1/e2ee-ct:<request hash>:<response hash>`, not the plaintext. The signature cannot be bound to the plaintext output client-side; receipts record `binding: e2ee-ciphertext` and proofs say so. |
| 3. Signature retention | Signatures were available at 0, 5 and 15 minutes and gone (`chat_id_not_found`) by 30 minutes. Fetch and store them right after the call; `lore_check_proof` must rely on the stored receipt. |
| 4. Embeddings | `qwen3-embedding-8b` works privately on `/v1/embeddings` (4096 dims), signed the same E2EE way by a mainnet provider. |
| 5. Storage from Python | **Works.** The pinned CLI launcher builds with Go 1.24; `storage_roundtrip.py` passed on Galileo: 10.8 s upload (finalized), 1.6 s download with `--proof`. On Windows the CLI needs the profile env vars (fixed in `storage.py`). |
| 6. Attestation | `0g-compute-cli@0.9.0` (`@0gfoundation/0g-compute-ts-sdk`) `inference verify` passed for the mainnet `qwen3-embedding-8b` provider: signer matches the contract, Docker Compose hash valid, exit 0. Its steps 6-8 (image digests, dstack verifier) are manual, so exit 0 covers the automated checks only. The CLI reads its key only from `~/.0g-compute-cli/config.json`; a throwaway key works for verification. Two other providers did not answer at the time. |

## Answers for P1

**S2, provider lookup.** Read `getService(provider)` on 0G's Compute Inference
contract. It returns `(provider, serviceType, url, inputPrice, outputPrice,
updatedAt, model, verifiability, additionalInfo, teeSignerAddress,
teeSignerAcknowledged)`. [`provider_lookup.py`](provider_lookup.py) has the ABI, and
`expected_signer()` applies the plan's `targetSeparated` rule.

| Chain | Compute Inference contract | Services |
|---|---|---|
| 16661 mainnet | `0x47340d900bdFec2BD393c626E12ea0656F938d84` | [10](evidence/compute-services-16661.json) |
| 16602 testnet | `0xa79F4c8311FF93C06b8CfB403690cc987c93F91E` | [8](evidence/compute-services-16602.json) |

**The Router's providers appear to be on mainnet, not Galileo.** The Router's TeeML
models match the mainnet records (for example `glm-5.3`, `0GM-1.0-35B-A3B` and
`qwen3-embedding-8b`). This is an inference from matching catalogues; the docs do
not state it, and only a live `x_0g_trace.provider` can confirm it. Lore's contracts
stay on 16602, so `provider_info` and `lore_check_proof` need a separate mainnet read.

**S4, models.** [Router catalogue](evidence/router-models.json), fetched without a
key: 125 models. Filter on `verifiability == "TeeML"`.

- Chat: `glm-5.3`, `0gm-1.0-35b-a3b`, `0gm-1.0-35b-a3b-sia`.
- Embeddings: use `qwen3-embedding-8b`. `qwen3-embedding-0.6b` is listed by the Router
  but has no mainnet service record. `qwen3.7-text-embedding` is TeeTLS on the Router,
  though its on-chain record says TeeML, so don't use it.
- So a TeeML embedding model exists and `fastembed` should not be needed.

**Decision (2026-11-06): `ZG_MODEL=glm-5.3`, `ZG_EMBED_MODEL=qwen3-embedding-8b`.** Both are TeeML on the
Router and served by mainnet providers whose TEE signers match their on-chain records. `glm-5.3` ran the
verifier and curator through the full end-to-end run on Galileo: it caught the near-copy, wrote all titles and
descriptions within limits (with the curator's length-feedback retry), and its proofs pass. It reasons before
answering, so give it a generous `max_tokens` (or none) and a long read timeout (`zg` uses 300 s).
`deploy/run_local.py` defaults to `glm-5.3`; set `ZG_MODEL` the same way for `deploy/compose.yaml`.

## Status by question

| S item | Status | Evidence | Still needed |
|---|---|---|---|
| 1. Router from Python | Not run | [0G's privacy guide](https://0g.ai/blog/data-privacy-on-0g-private-computer) documents the client, header and `verify_tee`. | Router key. Run a synthetic prompt through `agents/zg`. |
| 2. Signature + signer | Partly answered | Contract and method above. One GET to a provider's `/v1/proxy/signature/<fake id>` returned `chat_id_not_found`, so the route exists although the [inference docs](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/inference) omit it. | A real chat ID: recover the signer, compare with `expected_signer`, and confirm signed text equals the output. |
| 3. Signature retention | Not run | The error text says "not found or expired", so retention is finite. Duration unknown. | Timed fetches of a real chat ID. Until then, `lore_check_proof` must rely on the stored receipt. |
| 4. Models + embeddings | Answered, except quality | Above. | Fixture quality check with a key. |
| 5. Storage from Python | Blocked | [SDK page](https://docs.0g.ai/developer-hub/building-on-0g/storage/sdk) lists only Go and TypeScript, so the route is the [official CLI](https://github.com/0gfoundation/0g-storage-client/blob/main/cli.md). `storage.py` is mock-tested. | Build the Go launcher, fund a wallet, run `storage_roundtrip.py` for latency. |
| 6. Attestation | Not run | [Docs](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/inference) describe `inference verify` but not its output format. `@0glabs/0g-serving-broker` is now a shim for `@0gfoundation/0g-compute-ts-sdk`. | Install a pinned CLI and run it on a real provider. |

If S1 or S2 fails live, stop and escalate to the team, as workstream S requires.
Missing credentials are an unrun check, not a pass or a failure. Never downgrade
private mode.

## P2 deployment

[`check_chain.py`](check_chain.py) passed against Galileo ([output](evidence/chain-16602.json)):
all 7 contracts have code, 8 wiring links are correct, and live parameters match
section 3.1. It is read-only. All roles still sit on the deployer address, so F needs
P2 to grant them to the generated wallets.

## Storage notes

The stock CLI takes the wallet key through `--key`, which exposes it in process
arguments, so `storage.py` passes it on stdin to a small launcher. That launcher is
written but not built. Download always uses `--proof`. Lore's AES-GCM blob must stay
intact; do not use the CLI's own `--encryption-key` format.

## Running the checks

```sh
python3.12 spike/preflight.py    # presence booleans only; exit 2 = prerequisites missing
uv run --project shared --locked --group platform python spike/check_chain.py
uv run --project shared --locked --group platform python spike/provider_lookup.py --chain-id 16661
uv run --project shared --locked --group platform python spike/storage_roundtrip.py  # needs CLI + funded key
```

Exit 0 from preflight means ready, not passed. Never paste keys into a command,
chat or evidence file. `spike/evidence/` is committed, so raw live output with
anything sensitive belongs in the ignored `spike/local-evidence/`.

## World ID (W1-W4), 2026-11-06

**Login does not work yet on `main`.** It fails at three separate points, in this order, and each one
alone blocks every real login. All three are in P1's files, so they are listed here and not fixed.

| # | Where | Failure |
|---|---|---|
| 1 | `gateway/worldid.py` `rp_context()` | Raises `NotImplementedError`, so `/login/request` returns 503. The port is ready (W1). |
| 2 | `gateway/app.py` login page | `IDKit.request` omits `allow_legacy_proofs`. The SDK throws `allow_legacy_proofs is required`. |
| 3 | `gateway/app.py` login page | `pollUntilCompletion()` returns `{success, result}` and the page posts all of it. `verify` then rejects it as "proof is for a different action". Post `.result`, and show `.error` when `success` is false. |

Deployment gaps (P3) **fixed**: `deploy/launch.py` now requires `WORLD_RP_SIGNING_KEY`
from the gateway-only mounted secret file, and `create_secrets.py` leaves an explicit
blank placeholder for the operator's registered RP key. The key is not placed in
Compose's public environment. `WORLD_IDKIT_MODULE` defaults to the pinned 4.6.0
ESM URL below. Existing installations must add the key before restart; see
[`deploy/RUNBOOK.md`](../deploy/RUNBOOK.md). This does not resolve the P1 login
failures above or constitute a live browser/World verification.

| Item | Status | Result |
|---|---|---|
| W1 signing | **Answered offline** | [`world_rp.py`](world_rp.py) is byte-identical to `signRequest` in `@worldcoin/idkit-core@4.6.0`, and the real SDK accepts its `rp_context`. Not yet accepted by World: that needs a registered key. |
| W1 module | **Partly answered** | Use `https://cdn.jsdelivr.net/npm/@worldcoin/idkit-core@4.6.0/+esm`: it exports `IDKit` and the presets. `dist/index.js` imports bare and `.cjs` paths, and `idkit.global.js` is not a module. jsDelivr says not to use SRI on `+esm`, so self-hosting a bundle is safer for a login page. Not loaded in a browser yet. |
| W2 device | **Answered from source** | `deviceLegacy` exists and asks World App for `verification_level: device`. 4.0 has no device credential (`proof_of_human`, `selfie`, `passport`, `mnc`), so device is 3.0 only. The page asks only for `orbLegacy` today. Whether `deviceLegacy` also accepts Orb users is unconfirmed. |
| W3 signal hash | **Answered** | `keccak256(bytes) >> 8`, which matches the gateway for login ids. A `0x`-hex signal is hashed as bytes, not text, so the gateway's `signal_hash` would be wrong if a wallet address became the signal again. |
| W3 nullifier across signals | **Expected, not run** | The docs say one person and one action give one nullifier. |
| W3 Orb vs device | **Answered from source, 3.0 only** | WalletKit's test asserts a device proof has the same nullifier as the Orb one, "to maintain a single representation of the user". Not checked with a real account. |
| W3 3.0 vs 4.0 | **Risk** | World's migration guide says "Track both nullifiers", so they should be treated as different. `proofOfHuman` can return either, which would give one human two person ids. Keep the gateway on 3.0 proofs only, as it is today, until there is a mapping. |
| W4 repeat proofs | **Open, and the main design risk** | Lore proves the same action at every login. World's docs call that "an anti-pattern" and point to session proofs. WalletKit's 4.0 path refuses a reused nullifier 10 minutes after first use, for a year, unless the RP is on a whitelist (WIP-113, empty by default). Its 3.0 path has no such guard, so 3.0 logins may repeat, but whether World's API or the action settings allow it is unconfirmed. |
| Environment | **Open, security** | The gateway forwards the browser's `environment` to World. The docs do not say a production app refuses `staging`. If it does not, free simulator identities become Lore people. Pin it on the server whatever World does. |

**How this was tested.** [`world/driver.mjs`](world/driver.mjs) runs the real SDK against a local bridge, which IDKit
allows for `app_staging_` apps. Its replies are simulated, so [the evidence](evidence/world-idkit-4.6.0.json) shows the
SDK's request and result shapes, never a real proof. One POST to `/api/v4/verify/rp_00000000000000ab` with no responses
returned a 400 `validation_error`, so the endpoint is live; nothing about Lore's app has been tested at World.

Run offline, from `agents/`: `uv run pytest ../spike/test_world_id.py` (needs `npm ci --ignore-scripts` in `spike/world`).
Each `xfail` is a gap above and fails once it is fixed, so the mark gets removed with the fix.
Run live with [`world_live.py`](world_live.py) once the app is registered. It covers W1, W3 and W4.

Sources: `@worldcoin/idkit-core` 4.6.0 and `@worldcoin/idkit-server` 1.2.0 (npm),
[WalletKit](https://github.com/worldcoin/walletkit) `crates/walletkit-core` at `main` (`v3/world_id.rs`,
`storage/cache/nullifiers.rs`, `authenticator/mod.rs`), and docs.world.org pages `world-id/4-0-migration`,
`world-id/idkit/session-proofs`, `world-id/idkit/signatures` and `api-reference/developer-portal/verify`.
