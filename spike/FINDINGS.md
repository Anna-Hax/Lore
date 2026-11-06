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
- So a TeeML embedding model exists and `fastembed` should not be needed. Quality on
  verifier and curator fixtures is untested.

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
