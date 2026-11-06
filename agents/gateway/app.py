"""Lore's one hosted service: the MCP server users connect to, plus the internal API for Lore's own agents.

    /mcp, /authorize, /token, /register, /.well-known/...   hosted MCP + OAuth (gateway/mcp_server.py, oauth.py)
    /login                                                  the World ID login page OAuth sends users to
    /internal/*                                             verifier and curator only (shared service secret)
    /api/overview                                           public, read-only explorer data (no plaintext)
    /app/                                                   the explorer UI (site/), when served from here

There is no other login: users are their World ID; Lore's own agents use LORE_SERVICE_TOKEN.

`content` and `storage` are P3's libraries. The gateway only needs:
    content.content_hash(text) -> "0x.."
    content.encrypt_node(text, content_hash) -> bytes
    content.decrypt_node(blob, content_hash) -> str
    content.watermark(text, wallet, ref) -> str       (ref: "node:<id>" for a buyer, "sub:<id>" for a voter)
    content.validate_plaintext(text)                  (ValueError: reserved watermark characters, bad UTF-8)
    storage.upload(data: bytes) -> "0x.." root
    storage.download(root) -> bytes
"""

import hmac
import html
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from eth_utils import keccak
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gateway.mcp_server import build_mcp
from gateway.oauth import WorldIDOAuth
from gateway.service import Service
from gateway.signer import Signer
from gateway.worldid import WorldIDError

LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Log in to Lore</title>
<style>body{font:16px system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem}a{word-break:break-all}
.app{padding:.75rem 1rem;border:1px solid #8884;border-radius:.5rem}.warn{color:#b45309}button{font:inherit;padding:.5rem 1.25rem}</style>
</head><body><h1>Log in to Lore with World ID</h1>
<div class="app"><p><b>__CLIENT__</b> is asking to act as you on Lore: read topics you bought, see your vote tasks,
and send Lore transactions from your Lore wallet.</p><p>After you approve, you will be sent to <b>__HOST__</b>.</p>__WARNING__</div>
<p>Only continue if you started this login from your own MCP client just now.</p>
<p><button id="go">Approve and verify with World ID</button></p>
<p id="s"></p><p><a id="l" hidden>Open in World App</a></p>
<script type="module">
const pending = new URLSearchParams(location.search).get("pending");
const say = t => document.getElementById("s").textContent = t;
document.getElementById("go").addEventListener("click", async (ev) => {
  ev.target.disabled = true;
  try {
    const r = await fetch("/login/request?pending=" + encodeURIComponent(pending)); const req = await r.json();
    if (!r.ok) throw new Error(req.detail || r.status);
    // ponytail: IDKit 4.0 core API as documented (IDKit.request + orbLegacy preset); pin and confirm in spike W1.
    const { IDKit, orbLegacy } = await import(req.idkit_module);
    const request = await IDKit.request({ app_id: req.app_id, action: req.action, rp_context: req.rp_context })
                               .preset(orbLegacy({ signal: req.signal }));
    const a = document.getElementById("l"); a.href = request.connectorURI; a.hidden = false;
    say("Open this link with World App on your phone (or scan it there), then approve.");
    const result = await request.pollUntilCompletion();
    say("Checking your proof\\u2026");
    const done = await fetch("/login/complete?pending=" + encodeURIComponent(pending),
                             { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(result) });
    const body = await done.json();
    if (!done.ok) throw new Error(body.detail || done.status);
    say("Logged in. Returning to your MCP client\\u2026"); location.href = body.redirect;  // scheme checked server-side
  } catch (e) { say("Login failed: " + e.message); ev.target.disabled = false; }
});
</script></body></html>"""
WARNING = ('<p class="warn">This app is not on your own computer. If you did not start this login yourself, '
           'close this page: approving would give that app access to your Lore account.</p>')


DEMO_LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Demo login · Lore</title>
<style>body{font:16px system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem}
.app{padding:.75rem 1rem;border:1px solid #8884;border-radius:.5rem}.warn{color:#b45309}input,button{font:inherit;padding:.5rem}</style>
</head><body><h1>Lore demo login</h1>
<p class="warn"><b>Demo mode.</b> World ID is not configured on this gateway, so it runs Lore's demo login: each name
you type is one demo person. Production gateways log in with World ID only.</p>
<div class="app"><p><b>__CLIENT__</b> is asking to act as you on Lore.</p><p>After you approve, you will be sent to
<b>__HOST__</b>.</p>__WARNING__</div>
<form id="f"><p><label>Demo person name <input id="n" required maxlength="64" autocomplete="off"></label></p>
<p><button>Approve</button></p></form><p id="s"></p>
<script>
const pending = new URLSearchParams(location.search).get("pending");
document.getElementById("f").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const r = await fetch("/login/demo?pending=" + encodeURIComponent(pending), {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify({name: document.getElementById("n").value})});
  const body = await r.json();
  if (!r.ok) { document.getElementById("s").textContent = "Login failed: " + (body.detail || r.status); return; }
  location.href = body.redirect;
});
</script></body></html>"""


def demo_person(name: str) -> str:
    """A demo person id: same 0x-bytes32 shape as a World ID nullifier, derived from a name."""
    return "0x" + keccak(("lore-demo-person:" + name.strip().lower()).encode()).hex()


def login_page(p: dict, demo: bool = False) -> str:
    """The consent screen. Every value from the client is escaped: client names are attacker-chosen."""
    return ((DEMO_LOGIN_PAGE if demo else LOGIN_PAGE).replace("__CLIENT__", html.escape(p["client_name"]))
            .replace("__HOST__", html.escape(p["redirect_host"]))
            .replace("__WARNING__", "" if p["local"] else WARNING))


def create_app(db_path: str, chain, content, storage, now=lambda: int(time.time()), *, world=None,
               service_token: str | None = None, public_url: str = "http://127.0.0.1:8080",
               provider_signer=None, turnkey=None, demo_login: bool = False, site_dir: str | None = None,
               chain_info: dict | None = None, warm_overview: bool = False) -> FastAPI:
    """world: gateway.worldid.WorldID (None: nobody can log in, unless demo_login). service_token: the verifier/curator
    secret. turnkey: gateway.turnkey.Turnkey (None: no wallets, so nothing can be signed). demo_login: only when World
    ID is not configured, a clearly labelled name-based demo login (testnet demos)."""
    service = Service(db_path, chain, content, storage, now, provider_signer, turnkey)
    if turnkey is not None:
        service.signer = Signer(chain, turnkey, service.managed_sub_org)
    oauth = WorldIDOAuth(db_path, public_url, now)
    mcp = build_mcp(service, oauth, public_url)
    mcp_app = mcp.streamable_http_app(host="0.0.0.0")  # also creates the session manager the lifespan runs

    @asynccontextmanager
    async def lifespan(_):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Lore gateway", lifespan=lifespan)
    app.state.service, app.state.oauth, app.state.mcp = service, oauth, mcp

    # --- Lore's own agents: shared service secret, compared in constant time ---
    def lore_service(authorization: str = Header(None)) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not service_token or not hmac.compare_digest(given.encode(), service_token.encode()):
            raise HTTPException(401, "Lore service token required")

    @app.get("/internal/plaintext/{kind}/{iid}", dependencies=[Depends(lore_service)])
    def internal_plaintext(kind: str, iid: int):
        if kind not in ("sub", "node"):
            raise HTTPException(404, "kind must be sub or node")
        try:
            return service.internal_plaintext(kind, iid)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/internal/candidates/{tid}", dependencies=[Depends(lore_service)])
    def internal_candidates(tid: int):
        return service.internal_candidates(tid)

    @app.get("/internal/topics/{tid}", dependencies=[Depends(lore_service)])
    def internal_topic(tid: int):
        try:
            return service.topic(tid)
        except Exception as e:
            raise HTTPException(404, str(e)) from e

    # --- public explorer API: read-only, no plaintext, cached briefly (storage reads are slow) ---
    overview_cache = {"at": 0.0, "data": None}
    overview_lock = threading.Lock()

    def refresh_overview():
        data = service.overview(chain_info or {}, chain.params(), public_url.rstrip("/") + "/mcp")
        with overview_lock:
            overview_cache["data"], overview_cache["at"] = data, time.time()
        return data

    if warm_overview:  # keep it fresh in the background: the first build downloads receipts from 0G Storage (slow)
        def warm():
            while True:
                try:
                    refresh_overview()
                except Exception:  # RPC or storage blip: keep serving the last good copy
                    pass
                time.sleep(15)

        threading.Thread(target=warm, daemon=True, name="overview-warmer").start()

    @app.get("/api/overview")
    def api_overview():
        with overview_lock:
            data, at = overview_cache["data"], overview_cache["at"]
        if data is None or (not warm_overview and time.time() - at > 15):
            data = refresh_overview()
        return JSONResponse(data, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    # --- World ID login (the OAuth authorize step sends users here) ---
    def pending_or_404(pending: str) -> dict:
        p = oauth.pending(pending)
        if p is None:
            raise HTTPException(404, "this login expired; start again from your MCP client")
        return p

    demo = demo_login and world is None

    @app.get("/login", response_class=HTMLResponse)
    def login(pending: str):
        return login_page(pending_or_404(pending), demo)

    @app.post("/login/demo")
    def login_demo(pending: str, body: dict):
        if not demo:
            raise HTTPException(404, "demo login is off")
        pending_or_404(pending)
        name = str(body.get("name", "")).strip()
        if not name or len(name) > 64:
            raise HTTPException(400, "give a demo person name (1-64 characters)")
        redirect = oauth.complete_login(pending, demo_person(name))
        if redirect is None:
            raise HTTPException(404, "this login expired; start again from your MCP client")
        return {"redirect": redirect}

    @app.get("/login/request")
    def login_request(pending: str):
        pending_or_404(pending)
        if world is None:
            raise HTTPException(503, "World ID is not configured on this gateway")
        try:
            return world.request(pending)  # the proof's signal is this login's own id
        except NotImplementedError as e:
            raise HTTPException(503, str(e)) from e

    @app.post("/login/complete")
    def login_complete(pending: str, result: dict):
        pending_or_404(pending)
        if world is None:
            raise HTTPException(503, "World ID is not configured on this gateway")
        try:
            person = world.verify(result, pending)
        except WorldIDError as e:
            raise HTTPException(400, str(e)) from e
        redirect = oauth.complete_login(pending, person)
        if redirect is None:  # expired or already used meanwhile
            raise HTTPException(404, "this login expired; start again from your MCP client")
        return {"redirect": redirect}

    if site_dir and Path(site_dir).is_dir():
        app.mount("/app", StaticFiles(directory=site_dir, html=True), name="site")
    app.mount("/", mcp_app)  # last: /mcp and the OAuth routes
    return app
