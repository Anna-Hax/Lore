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

## T1, Turnkey delegated access (2026-11-07)

`spike/turnkey_t1.py` against the live Turnkey API and Galileo: all 15 checks passed.

- The activity versions and result fields in `agents/gateway/turnkey.py` work as written. Resending a request with the same `timestampMs` returns the same sub-org and wallet.
- After setup, only the user is in the root quorum, and all 7 Lore policies exist.
- Allowed calls sign and recover to the wallet. The policy engine denies USDC approve to another spender, `transfer`, another contract, another chain id, native value and gas above `MAX_GAS`.
- A denial is an HTTP 403 ("insufficient permissions"), not a failed activity.
- The gateway's `Signer` path was mined on 16602: `0x0d1959a16e7b9effba4139ded0382f4aab79913f6b7536e0b3bacb483c3a89bb`.
- Not yet checked: whether the user can sign in to Turnkey with their email and revoke Lore.

## End-to-end with Turnkey wallets (2026-11-07)

`e2e/run.py` ran against the deployed contracts, with fresh service wallets that were granted roles. Every user transaction was signed by Turnkey.

**Passed:**
- Login, plus `lore_create_wallet` for four people: sub-orgs, policies, and the PersonRegistry link.
- A new topic accepted (sub 8, which became node 6 in topic 3).
- Two vote-gated follow-ups accepted (subs 9 and 11).
- A near-copy failed by the verifier and voted down (sub 10), with its whole 10 USDC stake going to the treasury.

**Stopped:** the run halted in the second topic. Turnkey answered 429 because the org was over its free signing quota. The market phase (buy, read, curator proof, leak trace, claim) did not run.

**Found and fixed during the run:**
- A new wallet wasn't usable until the indexer saw its registration.
- `check_roles.py` crashed on the Turnkey key in `addresses.json`.
- The e2e demo names clashed with an earlier run's wallets.

**Found, operational:** a second set of Lore services running against the same contracts (a teammate's) reported first and failed our submission.

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
`qwen3-embedding-8b`). The live S1 run confirmed it: `x_0g_trace.provider` was a mainnet
service. Lore's contracts
stay on 16602, so `provider_info` and `lore_check_proof` need a separate mainnet read.

**S4, models.** [Router catalogue](evidence/router-models.json), fetched without a
key: 125 models. Filter on `verifiability == "TeeML"`.

- Chat: `glm-5.3`, `0gm-1.0-35b-a3b`, `0gm-1.0-35b-a3b-sia`.
- Embeddings: use `qwen3-embedding-8b`. `qwen3-embedding-0.6b` is listed by the Router
  but has no mainnet service record. `qwen3.7-text-embedding` is TeeTLS on the Router,
  though its on-chain record says TeeML, so don't use it.
- So a TeeML embedding model exists and `fastembed` should not be needed. Quality on
  verifier and curator fixtures is untested.

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
built locally by `shared/storage_cli/build.py` and in Docker by `deploy/Dockerfile`. Download always uses `--proof`. Lore's AES-GCM blob must stay
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
