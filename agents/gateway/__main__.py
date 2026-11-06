"""Run the gateway: `uv run python -m gateway`.

Env: LORE_CHAIN_ID (default 16602, P2's Galileo deployment), LORE_RPC (optional override),
LORE_GATEWAY_KEY (gateway wallet: holds LEAK_DETECTOR and REGISTRAR, pays finalize and registration gas),
WORLD_APP_ID, WORLD_RP_ID, WORLD_RP_SIGNING_KEY, WORLD_ACTION, WORLD_IDKIT_MODULE (see gateway/worldid.py),
LORE_PUBLIC_URL (where users reach the hosted MCP, e.g. https://lore.example; the MCP is at /mcp),
LORE_SERVICE_TOKEN (the secret the verifier and curator send to /internal/*),
TURNKEY_ORGANIZATION_ID, TURNKEY_API_PUBLIC_KEY, TURNKEY_API_PRIVATE_KEY (Lore's Turnkey parent org key),
TURNKEY_DELEGATED_PUBLIC_KEY, TURNKEY_DELEGATED_PRIVATE_KEY (Lore's delegated user in each user's sub-org),
LORE_DB (sqlite path), LORE_PORT, plus whatever P3's lore_shared needs (MASTER_KEY, WM_SECRET, ...).
LORE_DEMO_LOGIN=1 enables the labelled name-based demo login, and only while WORLD_APP_ID is unset (testnet demos).
LORE_SITE_DIR (default ../site) is served at /app/.
"""

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import uvicorn

import shared
from chain import Chain
from gateway import worker
from gateway.app import create_app
from gateway.turnkey import Turnkey
from zg.providers import Providers
from gateway.db import bind_deployment, connect
from gateway.worldid import WorldID
from gateway.worldidp import WorldIdP


def self_signed(folder: Path) -> tuple[str, str]:
    """A localhost certificate for the local HTTPS listener, made once and reused."""
    cert, key = folder / "localhost.pem", folder / "localhost-key.pem"
    if not cert.exists():
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        folder.mkdir(parents=True, exist_ok=True)
        k = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.UTC)
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
             .not_valid_after(now + datetime.timedelta(days=30))
             .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
             .sign(k, hashes.SHA256()))
        key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
        cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return str(cert), str(key)


def main():
    from lore_shared import crypto, leak, storage, watermark

    content = SimpleNamespace(
        content_hash=crypto.content_hash, encrypt_node=lambda text, _content_hash: crypto.encrypt_node(text),
        decrypt_node=crypto.decrypt_node, watermark=watermark.watermark,
        validate_plaintext=watermark.validate_plaintext,
    )
    chain_id = int(os.environ.get("LORE_CHAIN_ID", 16602))
    dep = shared.deployment(chain_id)
    chain = Chain.for_chain(chain_id, os.environ["LORE_GATEWAY_KEY"], os.environ.get("LORE_RPC"))
    db_path = os.environ.get("LORE_DB", "gateway.db")
    bind_deployment(connect(db_path), shared.deployment_key(chain_id))  # refuse a db from another deployment

    threading.Thread(
        target=worker.run, args=(db_path, chain, storage, leak.best_match, dep["deployBlock"]), daemon=True
    ).start()
    world = None
    if os.environ.get("WORLD_APP_ID"):
        world = WorldID(os.environ["WORLD_APP_ID"], os.environ["WORLD_RP_ID"], os.environ.get("WORLD_ACTION", "lore-person"),
                        os.environ.get("WORLD_RP_SIGNING_KEY"), os.environ.get("WORLD_IDKIT_MODULE"))
    net = shared.network(chain_id)
    chain_info = {"chain_id": chain_id, "name": net.name, "explorer": net.explorer, "contracts": dep["contracts"]}
    site_dir = os.environ.get("LORE_SITE_DIR", str(Path(__file__).resolve().parents[2] / "site"))
    providers = Providers(int(os.environ.get("ZG_PROVIDER_CHAIN_ID", 16661)))  # spike S2: 0G mainnet
    e = os.environ
    turnkey = Turnkey(e["TURNKEY_ORGANIZATION_ID"], (e["TURNKEY_API_PUBLIC_KEY"], e["TURNKEY_API_PRIVATE_KEY"]),
                      (e["TURNKEY_DELEGATED_PUBLIC_KEY"], e["TURNKEY_DELEGATED_PRIVATE_KEY"]))
    idp = None
    tls_port = int(e.get("LORE_TLS_PORT", 0) or 0)
    approve_base = e.get("LORE_APPROVE_URL") or (f"https://localhost:{tls_port}" if tls_port else e["LORE_PUBLIC_URL"])
    if e.get("WORLD_IDP_CLIENT_ID"):  # World ID Agent Pass: login + human checkpoints
        idp = WorldIdP(e.get("WORLD_IDP_ISSUER", "https://auth.world.org"), e["WORLD_IDP_CLIENT_ID"],
                       e["WORLD_IDP_CLIENT_SECRET"], approve_base.rstrip("/") + "/login/callback")
    app = create_app(db_path, chain, content, storage, world=world, service_token=e["LORE_SERVICE_TOKEN"],
                     public_url=e["LORE_PUBLIC_URL"], provider_signer=lambda p: providers(p)[1], turnkey=turnkey,
                     demo_login=e.get("LORE_DEMO_LOGIN") == "1", site_dir=site_dir, chain_info=chain_info,
                     warm_overview=True, idp=idp, approve_base=approve_base)
    port = int(os.environ.get("LORE_PORT", 8080))
    if not tls_port:
        uvicorn.run(app, host="0.0.0.0", port=port)
        return
    # Also serve HTTPS (World IdP only redirects to https callbacks). One app, two listeners; lifespan runs once.
    import asyncio

    plain = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port))
    cert, key = e.get("LORE_TLS_CERT"), e.get("LORE_TLS_KEY")
    if not cert:  # local demo: a self-signed certificate for localhost (the browser warns once)
        cert, key = self_signed(Path(db_path).resolve().parent / "tls")
    tls = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=tls_port, lifespan="off",
                                        ssl_certfile=cert, ssl_keyfile=key))

    async def both():
        await asyncio.gather(plain.serve(), tls.serve())

    asyncio.run(both())


if __name__ == "__main__":
    main()
