"""Link this agent to the user's World ID, from the user's own machine.

lore_verify_world_id starts a page on 127.0.0.1. The page gets a signed request from Lore's gateway,
asks World App for a proof bound to this agent's address (IDKit), and hands the proof back here; this
process then sends it to the gateway, which verifies it with World and records agent -> person on-chain.
The page only ever talks to this local process and to World; the user's key never leaves this process.
"""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Lore: verify World ID</title>
<style>body{font:16px system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem}a{word-break:break-all}</style>
</head><body><h1>Verify your World ID for Lore</h1><p id="s">Preparing&hellip;</p><p><a id="l" hidden>Open in World App</a></p>
<script type="module">
const say = t => document.getElementById("s").textContent = t;
try {
  const r = await fetch("/request?t=TOKEN"); const req = await r.json();
  if (!r.ok) throw new Error(req.error || r.status);
  // ponytail: IDKit 4.0 core API as documented (IDKit.request + orbLegacy preset); pin and confirm in spike W1.
  const { IDKit, orbLegacy } = await import(req.idkit_module);
  const request = await IDKit.request({ app_id: req.app_id, action: req.action, rp_context: req.rp_context })
                             .preset(orbLegacy({ signal: req.signal }));
  const a = document.getElementById("l"); a.href = request.connectorURI; a.hidden = false;
  say("Open this link with World App on your phone (or scan it there), then approve.");
  const result = await request.pollUntilCompletion();
  say("Checking your proof with Lore…");
  const done = await fetch("/result?t=TOKEN", { method: "POST", body: JSON.stringify(result) });
  const body = await done.json();
  say(done.ok ? "Done. This agent is now linked to your World ID. You can close this tab." : "Failed: " + body.error);
} catch (e) { say("Failed: " + e.message); }
</script></body></html>"""


class Verification:
    """One local verification page. gw(method, path, **kw) is lore-mcp's signed-in gateway call."""

    def __init__(self, gw):
        self.gw, self.token, self.outcome = gw, secrets.token_urlsafe(16), None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/?t={self.token}"

    def _handler(self):
        v = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # stdout belongs to the MCP transport
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self):  # only the page we handed out (its URL carries the token) may use this server
                return self.path.split("t=", 1)[-1] == v.token

            def do_GET(self):
                if not self._authorized():
                    return self._send(403, {"error": "forbidden"})
                if self.path.startswith("/request"):
                    try:
                        return self._send(200, v.gw("GET", "/identity/request"))
                    except Exception as e:
                        return self._send(503, {"error": str(e)})
                self._send(200, PAGE.replace("TOKEN", v.token), "text/html; charset=utf-8")

            def do_POST(self):
                if not self._authorized() or not self.path.startswith("/result"):
                    return self._send(403, {"error": "forbidden"})
                n = int(self.headers.get("Content-Length", 0))
                try:
                    result = json.loads(self.rfile.read(min(n, 1_000_000)))
                    v.outcome = v.gw("POST", "/identity/register", json=result)
                    self._send(200, v.outcome)
                except Exception as e:
                    v.outcome = {"error": str(e)}
                    self._send(400, v.outcome)

        return H

    def close(self):
        self.server.shutdown()
