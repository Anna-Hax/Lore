# World ID Agent Pass in Lore

Lore is a marketplace where AI agents spend real money for their person: they **stake 10 USDC** to submit research, **pay 5 USDC** to buy a topic, **vote** on what enters a topic, and **claim** royalties. Lore holds delegated signing access to each person's Turnkey wallet, so an agent could in principle spend without its human ever noticing.

World ID Agent Pass (World IdP, `https://auth.world.org`) is the human layer on top of that:

1. **Who is this agent acting for?** The hosted MCP server's login is World IdP (OIDC). Each agent's MCP session belongs to one World ID person, and that person's wallets are linked to them on-chain in `PersonRegistry` (one vote per person, however many agents they run).
2. **Is the human OK with this, right now?** Before Lore signs a stake, a purchase, a vote or a claim, the agent gets an approval link instead of a transaction. The person must complete a **fresh** World ID authentication for that one action. Only then does `lore_continue` sign and send.

## The journey

| Step | Where | What happens |
|---|---|---|
| Request | agent → `lore_buy(topic_id=2, confirm=true)` | Lore prepares the transactions but signs nothing; returns `human_approval_required` with `approve_url` |
| Approval page | `https://<gateway>/checkpoint/<id>` | Shows exactly what the agent wants ("pay 5 USDC for topic 2"), with Approve / Deny |
| Verification | World IdP authorize: code flow, PKCE S256, `state`, `nonce`, `max_age=0`, `prompt=login`, `acr` essential (Orb) | The person authenticates again with World ID |
| Validation (backend) | `/login/callback` | `state` single-use; RFC 9207 `iss`; code redeemed with `client_secret_basic`; ID token RS256 via JWKS; `iss`, `aud`, `exp`, `nonce`, `acr`; `auth_time` must fall inside this attempt; `sub` must be the person who owns the agent |
| Protected action | agent → `lore_continue(checkpoint_id)` | Lore signs with Turnkey and sends; the approval is single-use and expires 5 minutes after approval |

### Unsuccessful paths (all leave the action unsent)

| Path | Result |
|---|---|
| Continue before approving | `waiting_for_approval`, nothing sent |
| Person presses **Deny** | `blocked: this action was denied (denied by the person)` |
| Cancelled at World IdP (`error=access_denied`) or class unavailable (`unmet_authentication_requirements`) | denied with that reason |
| A different World ID approves | denied ("a different World ID approved") |
| Old session instead of a fresh check (`auth_time` before the attempt) | denied |
| Forged / wrong-audience / replayed-nonce / wrong-class ID token | denied |
| Not approved within 10 minutes, or approval unused for 5 minutes | `expired` |
| Approval replayed after use | `blocked: this action was used` |
| Callback `state` replayed | rejected (400) |

All of these are covered by `agents/tests/test_worldidp.py` (a fake IdP signing real RS256 tokens).

### Live run on 0G Galileo (2026-11-07)

- Login through World IdP (production, `https://auth.world.org`), ID token validated in the gateway, MCP token issued to the World ID person.
- `lore_create_wallet` made a Turnkey wallet `0x717df246b538588021d4002f91bfa9e82a9bef49`, linked on-chain to the person in `PersonRegistry`.
- **Approved:** "pay 5 USDC for topic 2" → fresh World ID (Orb class) → `lore_continue` sent
  `0x1db4cfda…5bd9` (USDC approve) and `0x97c6078f…5a84` (Access.buy). Balance 20 → 15 USDC, `hasAccess(2) = true`.
- **Replay:** `lore_continue` on the used approval → blocked, nothing sent.
- **Denied:** "pay 5 USDC for topic 1" → person pressed Deny → `lore_continue` blocked; balance stayed 15 USDC, `hasAccess(1) = false`.

No client secret ever reaches the browser or the agent: it lives in the gateway's secret file, and the browser only ever carries `state` and the authorization code.

## Integration debrief

**Time to first success:** about 2 hours from opening the portal to the first validated login, and about 20 more minutes to the first approved and denied agent actions. The code itself (OIDC client, checkpoints, tests) took well under an hour; the rest was configuration friction.

**Friction we hit**

1. **`account_not_eligible` in the portal.** The portal sign-in worked but registration was refused until the right Google account was used. The error is documented only in a troubleshooting table.
2. **HTTPS-only callbacks, including for localhost.** `http://127.0.0.1` is rejected at registration, so a local demo needs its own TLS listener (we serve a self-signed `https://localhost:8443`). The rule is stated, but a localhost exception (as many IdPs allow) would remove a whole step.
3. **Opaque `reason=client` error page.** A redirect URI mismatch shows "This app's authentication configuration is incorrect"; the useful detail (`invalid_request`, exact redirect URI match) is behind "Developer details".
4. **Credential classes differ between docs and production.** The docs list `selfie` and `selfie-face`, but production discovery advertises only `orb` and `orb-face`; requesting Selfie Check returns `unmet_authentication_requirements` with no hint that it is not enabled for the client.
5. **Short-lived attempts for first-time users.** Account creation inside the flow ("Are you a returning user?") took longer than our original 10-minute login window; we raised it to 30 minutes.
6. **Some guides failed to load** for us (the MCP authorization guide rendered only "Loading World IdP"), so we built the MCP-side flow from the OIDC and step-up guides.

**Missing capability or documentation**

- A per-client view in the portal of which credential classes are actually available, and why a class is unmet.
- A documented localhost/loopback callback exception for development.
- An end-to-end example of step-up for an *agent action* (approval bound to one operation) rather than for a page load; the building blocks (`max_age=0`, `auth_time`, `sub` binding) are documented but scattered.

**The one improvement with the greatest impact:** a first-class "approve this action" request: let the relying party pass a short, signed description of the operation (e.g. "pay 5 USDC for topic 2") that World IdP shows to the person and returns as a signed claim in the ID token. Today the action binding lives only in our database; with it, the person's approval would be cryptographically tied to exactly what the agent will do.

## Configuration

`deploy/secrets/public.env` (git-ignored): `WORLD_IDP_ISSUER`, `WORLD_IDP_CLIENT_ID`, `WORLD_IDP_ACR` (`orb,orb-face` by default; `selfie,selfie-face` once enabled; `any`), `LORE_TLS_PORT=8443`. `deploy/secrets/gateway.env`: `WORLD_IDP_CLIENT_SECRET`. Register `https://localhost:8443/login/callback` (or your HTTPS host) as a callback in `https://auth.world.org/portal`. While World IdP is configured, the demo login is off.
