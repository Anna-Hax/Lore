# Lore hosting runbook

Runs the gateway, verifier and curator on one Docker host. The gateway is also the hosted MCP server
users connect to (`$LORE_PUBLIC_URL/mcp`, World ID login). Status: the compose file and image are not yet run on a real host.

## Before the first deploy

These need people or credentials, so they are not automated:

- `agents/` merged, with P1's wiring from `e2e/DELIVERY_HANDOFF.md`.
- `shared/storage_cli/bin/lore-storage-client` built (`python shared/storage_cli/build.py`).
- A host chosen, with Docker Compose. Create a `lore` user with uid 10001.
- A 0G Router API key created with `trust_mode: "private"`.

## First deploy

```sh
cd deploy
python create_secrets.py                  # refuses to overwrite; prints addresses only
# Add ZG_API_KEY to secrets/verifier.env and secrets/curator.env.
# Fund every wallet in secrets/addresses.json with testnet 0G: https://faucet.0g.ai
# Ask P2 to grant roles: gateway=LEAK_DETECTOR, verifier=VERIFIER, curator=CURATOR.
python check_roles.py                     # exit 0 only when roles and gas are in place
mkdir -p state/gateway state/verifier state/curator
sudo chown -R 10001:10001 state
ZG_MODEL=glm-5.3 docker compose up -d --build
```

The gateway binds to `127.0.0.1:8080`. Put a TLS reverse proxy in front of it.
Back up `secrets/` and `state/` off the host; `MASTER_KEY` loss loses all content.

## Redeploy

```sh
git pull
ZG_MODEL=glm-5.3 docker compose up -d --build
docker compose ps
```

Each service keeps its sqlite state in `state/<service>/`, so a redeploy resumes
from its last indexed block.

## Reading logs

```sh
docker compose logs -f --tail=100 gateway    # or verifier, curator
journalctl -u lore-attest.service -n 50
```

Logs must never hold plaintext or keys. If you see either, treat that key as
exposed and rotate it.

## Rotating secrets

| Secret | How | Warning |
|---|---|---|
| `ZG_API_KEY` | Create a new private-mode key, edit the env files, `docker compose up -d`. | Keep `trust_mode: "private"`. |
| Storage wallets | Put a new funded key in the service's env file and restart. | Safe at any time. |
| Role wallets | P2 grants the role to the new address, restart, then P2 revokes the old one. | Don't revoke first. |
| `MASTER_KEY` | **Do not rotate in v1.** | Blobs have no key version; old content becomes unreadable. |
| `WM_SECRET` | **Do not rotate in v1.** | Marks have no key version; past deliveries become untraceable. |

If `MASTER_KEY` or `WM_SECRET` is exposed, stop the gateway and raise it with the
team. Recovery needs a migration that v1 does not have.

## Daily provider attestation

Install the CLI (`@0gfoundation/0g-compute-ts-sdk`; `@0glabs/0g-serving-broker` is
a deprecated shim), pin the version, and confirm `0g-compute-cli inference verify
--help` works. Providers are registered on mainnet, so check the CLI targets it.

```sh
sudo cp lore-attest.service lore-attest.timer /etc/systemd/system/
sudo systemctl enable --now lore-attest.timer
```

The job reads receipts through the gateway and publishes CLI output to 0G Storage
with its own wallet. Fund the `attestation` wallet. It has not run against a real
provider yet.

## End-to-end check

Run `e2e/run.py` against the deployment, twice from a fresh deploy (M4). See its
docstring for the wallets and settings it needs.
