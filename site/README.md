# Lore web UI

The site is plain HTML, CSS and JavaScript, served by the gateway at `/app/`.

- `index.html`: landing page and overview of Lore.
- `explore.html#topics` and `#submissions`: public topic graphs, metadata, submission status and proof badges from `/api/overview`.
- `login.html`: branded World ID entry. On a gateway it starts the existing OAuth/PKCE flow, which reaches the gateway's `/login` route. The static preview asks for a gateway address and never pretends to verify a person.
- `workspace.html#account`: the signed-in person's wallets, browser-wallet linking, Turnkey wallet creation, claimable royalties and claims. Identity status comes from `lore_whoami` after World ID login.
- `workspace.html#topic/<id>`: buy a topic pass or read the watermarked copy after gateway access checks. The explorer links here; there is no duplicate workspace topic catalog.
- `workspace.html#agent`: hosted MCP endpoint, Claude Code command and a collapsed reference for all 18 user tools.
- `workspace.html#activity`: leak matches and human checkpoints. One-time approval continuation appears when this tab has a pending checkpoint.
- `workspace.html#contracts`: addresses and chain explorer links.

Research submission, voting, leak reporting and receipt verification stay in the user's MCP-capable agent. They have no human action form. The browser never calls `/internal/*`.

For a local preview:

```sh
python3 -m http.server 4173 --directory site --bind 127.0.0.1
```

Open `http://127.0.0.1:4173/`. Public data falls back to a clearly labelled saved snapshot; private account data is only loaded on the gateway after sign-in. The gateway serves the same files under `/app/`.

The browser client uses dynamic OAuth registration, PKCE, the gateway's World ID login, and the MCP 2025-11-25 handshake. Tokens live in tab-scoped session storage. It never stores research text in browser storage. A purchase or royalty claim requires review; a gateway approval request leads to its one-time World ID checkpoint. Self-held transactions are signed in the browser wallet, sent sequentially, and checked for successful receipts before the next is sent. Failures do not trigger retries.

## Browser checks

```sh
PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
GATEWAY_PYTHON="$PWD/agents/.venv/bin/python" \
node --test e2e/test_ui.mjs
```

The gateway fixture uses a temporary database, fake chain/storage and explicit demo login. It tests OAuth/MCP integration, not real World proofs or testnet transactions. Other checks intercept network calls and verify navigation, wallet linking, action review, access refusal and responsive layouts.
