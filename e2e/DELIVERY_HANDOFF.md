# Typed delivery watermarks: P3 review notes

Read `BUILD_PLAN.md` section C for the updated library contract. Section 3 and
all P1/P2 implementation paths are unchanged. This is an offline library change;
it does not implement the gateway, delivery database, `recordMatch`, or MCP.

## What P1 must wire

1. At `/ingest`, call `validate_plaintext(text)` before encryption or upload.
   Map `ValueError` to a client error. Already-marked research and invalid UTF-8
   must not reach storage. `watermark()` repeats validation as defense in depth.
2. After the on-chain vote-eligibility check, watermark only the task's text with
   `sub:<subId>`. Keep the report, receipts and parent metadata unchanged.
3. After the on-chain topic-access check, watermark each purchased node with
   `node:<nodeId>`. Role-protected `/internal/*` remains unwatermarked.
4. Persist `(wallet, topic_id, ref)` for every user delivery, with a unique key
   over all three fields. Make the log durable before exposing the copy; a log
   failure must not produce an untraceable user response. Keep `sub:` entries
   when submissions are accepted or rejected. Do not replace them with node refs.
5. Leak candidates are all `(wallet, ref)` deliveries in the reported topic,
   not just purchasers. Unpack `wallet, ref, score_bps`; only wallet and score
   belong in `recordMatch`. Keep the matched ref for off-chain diagnostics.
6. Handle `(None, None, 0)` explicitly. Never fall back to a nearby wallet or
   pass `None` into the ABI. P1/P2 must settle unmatched-report handling (leave
   unmatched or use a supported zero-address sentinel). No contract change here.

The matching function requires one exact complete mark before a candidate can
win. It then ranks qualifying candidates by the original fraction of matching
bits. Random marks, near matches and real marks from absent candidates yield
no attribution. Mixed node/submission excerpts can still match below 10000.
An authentic mark can be copied by someone who sees it; exact matching does not
prove who leaked the content. This remains a v1 forensic signal.

## P1's code against this library

`origin/p1/agents` at `95c8b20` was written against the earlier contract, so it
does not run with these libraries yet. These are for P1 to change; P3 has not
touched `agents/`:

| Where | Today | Needs |
|---|---|---|
| `gateway/__main__.py` | `encrypt_node=crypto.encrypt_node`, called with `(text, ch)` | `crypto.encrypt_node(text)`; it takes no hash argument |
| `gateway/app.py` | `watermark(..., addr, -sid)` and `watermark(..., addr, n["id"])` | refs `f"sub:{sid}"` and `f"node:{id}"` |
| `gateway/app.py` `/ingest` | no validation | `validate_plaintext`, returning a 4xx |
| `gateway/worker.py` `candidates_for` | `(wallet, int)` pairs | `(wallet, ref)` pairs |
| `gateway/worker.py` `match_leaks` | `wallet, score = best_match(...)` | `wallet, ref, score = ...`, handling `None` |
| `consts.py` `MIN_LEAK_SCORE_BPS` | 7000 gate | drop it: exact marks are the gate, and real mixed excerpts can score lower |
| `runtime.provider_info` | stub | spike S2: read `getService` on **mainnet** (`spike/FINDINGS.md`) |
| `runtime.embed` | stub | spike S4: `qwen3-embedding-8b` |
| `lore-mcp` `provider_signer` | stub | spike S2, same read |
| `pyproject.toml` | no `lore-shared` dependency | add it; `deploy/Dockerfile` installs it meanwhile |

`lore-mcp` also has no tool for `claimSlash`, so voters cannot pull slash rewards
through MCP.

## Checks

From the repository root:

```sh
uv run --project shared --python 3.12 --locked --group platform pytest shared/tests e2e deploy/test_deploy.py spike/test_preflight.py
```

`test_delivery_watermarks.py` covers library scenarios, not live endpoints.

`test_gateway_integration.py` runs P1's real gateway with the real crypto,
watermark and leak code, using P1's fake chain and storage. It skips until
`agents/` and the wiring above are in place. It passed on 2026-11-06, with P1's
own tests (61 total), on a scratch copy of P1's branch with that wiring applied.
That scratch change is not in this repository.

P1 still needs tests proving: ineligible voters get no plaintext; eligible
wallets get distinct task text with identical visible content; logs are
idempotent; a voter fetches a task, the submission is accepted, and its later
excerpt causes the gateway to record that voter. Test rejected submissions too.

## Limits to keep in mind

- Typed refs intentionally break old marks. No legacy fallback is added. Agree a
  migration before rotating secrets or changing a deployed marking format.
- Markdown protection is limited to ordinary inline backticks and fenced code,
  not a full syntax parser. Code-only excerpts are unmarked; unformatted source
  must have marks removed before execution. Document size increases with marking.
