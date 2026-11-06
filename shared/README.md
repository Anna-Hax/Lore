# lore-shared

P3's Python 3.12 package for P1's hosted gateway, which is also the MCP server users connect to.
Users' agents never receive `MASTER_KEY` or `WM_SECRET`.

From the repository root, with `uv` installed:

```sh
uv sync --project shared --python 3.12 --locked
uv run --project shared --python 3.12 --locked --group platform pytest shared/tests e2e deploy/test_deploy.py spike/test_preflight.py
```

This package is independently installable while the root uv workspace is still
absent. Add `shared` as a workspace member when the team creates it. No P1/P2
paths or frozen plan interfaces are changed here. `uv.lock` records the tested
dependency versions; runtime requirements are in `pyproject.toml`.

## Gateway handoff

```python
from lore_shared.canonical import canonical_hash, canonical_json
from lore_shared.crypto import content_hash, encrypt_node, decrypt_node
from lore_shared.watermark import validate_plaintext, watermark
from lore_shared.leak import best_match

# MASTER_KEY and WM_SECRET: independent random 32-byte keys, hex encoded in env.
validate_plaintext(text)  # /ingest: map ValueError to a client error before upload
digest = content_hash(text)
blob = encrypt_node(text)  # upload these bytes, never the plaintext

# ONLY after a fresh on-chain access check at the gateway endpoint:
plaintext = decrypt_node(blob, digest)
delivered = watermark(plaintext, buyer_wallet, f"node:{node_id}")

# ONLY after a fresh on-chain vote-eligibility check:
vote_copy = watermark(submission_text, voter_wallet, f"sub:{sub_id}")

wallet, ref, score_bps = best_match(leaked_excerpt, [
    (buyer_wallet, f"node:{node_id}"),
    (voter_wallet, f"sub:{sub_id}"),
])
# wallet/ref are None when no candidate has an exact complete mark.

metadata_bytes = canonical_json(metadata).encode("utf-8")
metadata_hash = canonical_hash(metadata)
```

Explicit `master_key=bytes` and `wm_secret=bytes` keyword arguments support the
host's secret store and isolated tests. Otherwise keys are loaded from the
environment at call time. There are no default keys. The library does not load
`.env` files or log content/secrets. The calling service owns secret loading.

The crypto and watermark helpers are primitives, not access-control endpoints.
P1 must test access, voting eligibility and role checks before every plaintext
response, including internal routes. Never cache those authorization decisions.

## Encoding details for interoperable callers

- Hashes are lowercase `0x`-prefixed Ethereum Keccak-256, not NIST SHA3-256.
- Canonical JSON uses recursively sorted string keys, compact separators and
  UTF-8 (`ensure_ascii=False`). Only JSON values and finite numbers are accepted.
  This is Python JSON serialization, not RFC 8785; other languages must match
  Python number serialization or use this helper. IDs remain strings per the plan.
- AES-256-GCM: HKDF-SHA256, no salt (RFC 5869 zero salt), 32-byte derived key,
  info `b"lore-node:" + lowercase_content_hash.encode("ascii")`. Each encryption
  has a fresh 12-byte IV. No AAD. Blob = IV + ciphertext + 16-byte GCM tag.
  Decryption also checks the recovered plaintext hash against the expected hash.
- Watermark input: 20 raw address bytes followed by the UTF-8 typed reference
  `node:<id>` or `sub:<id>`. HMAC-SHA256 truncated to 8 bytes, MSB first. U+200B encodes 0,
  U+200C encodes 1, and U+2063 frames each 64-bit mark. Addresses are case
  insensitive; IDs must be canonical positive decimal uint256 values with no
  leading zeros. Bare IDs are rejected. Marks follow sentence punctuation
  (including Chinese punctuation without spaces) and nonempty prose line ends.
  Ordinary Markdown backtick spans and backtick/tilde fences are protected.
  This is a limited Markdown scanner, not a full parser. Code-only excerpts have
  no marks; arbitrary unformatted code is not guaranteed executable. Strip marks
  before executing or otherwise processing a delivered document as source code.
- `validate_plaintext` rejects U+200B, U+200C and U+2063 anywhere in input,
  including code, plus invalid UTF-8 such as lone surrogates. No original text is
  silently rewritten. P1 must call it at ingest and return a client error; calling
  it only at delivery is too late. Legitimate use of these reserved characters
  (including zero-width non-joiners) is also rejected by this v1 policy.
- `score` counts complete framed marks; incomplete excerpt-boundary marks are
  ignored. No complete mark yields 0. Scores measure matching bits, not confidence;
  an unrelated wallet averages about 5000. Removing zero-width characters defeats
  v1. Do not use a nonzero score as proof of a leak or as an automatic penalty.
- `best_match` accepts `(wallet, ref)` pairs from every logged delivery in the
  topic, including vote-task copies. It returns `(wallet, ref, score_bps)` only if
  at least one complete mark exactly matches that candidate's HMAC. Otherwise it
  returns `(None, None, 0)`. This prevents fabricated or unrelated marks from
  naming whichever innocent wallet happens to have the highest bit similarity.
  Scores still count all decoded bits, so mixed-ref excerpts can score below
  10000. Equal scores break lexicographically by `(normalized_wallet, ref)`.
  Ties and copied authentic marks do not establish who leaked the text; v1 is an
  attribution signal, not tamper-proof evidence or grounds for automatic penalties.
- `Constants(**overrides)` holds per-application configurable defaults. Module
  constants are the plan's placeholders, not live on-chain configuration.
- `types.py` mirrors the frozen record shapes as `TypedDict`s; these are typing
  aids, not runtime validation or receipt verification.

`storage.py` wraps `lore-storage-client`, a small launcher around the official
CLI that takes the wallet key on stdin. Its Python side is tested with mocks. The
launcher itself (`storage_cli/`) has not been built, and no live upload has run.
Network configuration, ABIs and deployments belong to P2.

`chain.py` is read-only and needs the `platform` dependency group (`web3`).

## Migration and remaining integration

The typed-ref HMAC encoding is incompatible with earlier bare-node-ID marks.
This branch has not deployed that earlier format; there is no silent legacy
fallback. Any deployment that did issue old marks needs an explicit migration
before switching. P1 must log `(wallet, topic_id, ref)` idempotently for each user
delivery and retain `sub:` refs even when a submission is accepted or rejected.
Internal verifier/curator content stays unwatermarked and role-protected.

`MASTER_KEY` and `WM_SECRET` have no version in current blobs/marks. Replacing
either key loses the ability to decrypt or trace historical deliveries unless
the old key is retained and an explicit migration/version strategy is implemented.
Watermarks also increase document size and token usage; this is not measured as
an LLM token benchmark. See [delivery handoff](../e2e/DELIVERY_HANDOFF.md) for the
remaining P1 work and test boundaries.
