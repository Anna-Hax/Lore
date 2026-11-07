# Lore web UI

The site is plain HTML, CSS and JavaScript, served by the gateway at `/app/`.

- `index.html`: landing page and overview of Lore.
- `explore.html#topics` and `#submissions`: network totals, public topic graphs, metadata, submission status (compact rows, evidence on demand) and proof badges from `/api/overview`. Amounts are native 0G (wei), shown by `format.js`.
- `login.html`: branded World ID entry (Orb-verified only). On a gateway it starts the existing OAuth/PKCE flow, which reaches the gateway's `/login` route. The static preview asks for a gateway address (prefilled with `http://127.0.0.1:8080`) and never pretends to verify a person.
- `workspace.html#account`: a five-step guided setup (World ID, Lore wallet in your own Turnkey account, funding with 0G, comfy author token, connecting the agent), then royalties, locked author tokens, votes waiting for the agent, my topics and signed-in agents (with revoke).
- `workspace.html#topic/<id>`: buy a topic (the review shows the `lore_buy` quote: base price, authors' tokens, the 3% maximum and the 30-day token lock) or read the watermarked copy of a topic you own. The explorer links here; there is no duplicate workspace topic catalog.
- `workspace.html#agent`: hosted MCP endpoint, Claude Code command and a collapsed reference for all 24 user tools.
- `workspace.html#activity`: your own approvals (`lore_my_approvals`) with Approve and Continue, and public leak matches.
- `workspace.html#contracts`: addresses and chain explorer links.

Research submission, voting, leak reporting and receipt verification stay in the user's MCP-capable agent. They have no human action form. The browser never calls `/internal/*`, and never calls `lore_inbox` (it marks updates read, so the agent would miss them).

For a local preview:

```sh
python3 -m http.server 4173 --directory site --bind 127.0.0.1
```

Open `http://127.0.0.1:4173/`. Public data falls back to a clearly labelled saved snapshot; private account data is only loaded on the gateway after sign-in. The gateway serves the same files under `/app/`.

The browser client uses dynamic OAuth registration, PKCE, the gateway's World ID login, and the MCP 2025-11-25 handshake. Tokens live in tab-scoped session storage. It never stores research text in browser storage, and signing out clears personal data from the page before any network call. A purchase or claim requires review; the gateway then asks for a one-time World ID approval (listed under approvals) before Lore signs from the Turnkey wallet. Failures do not trigger retries.

## Browser checks

```sh
PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
GATEWAY_PYTHON="$PWD/agents/.venv/bin/python" \
node --test e2e/test_ui.mjs
```

The gateway fixture uses a temporary database, fake chain/storage and explicit demo login. It tests OAuth/MCP integration, not real World proofs or testnet transactions. Other checks intercept network calls and verify navigation, wallet linking, action review, access refusal and responsive layouts.
