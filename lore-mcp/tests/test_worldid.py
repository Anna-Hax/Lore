import json
import urllib.error
import urllib.request

from lore_mcp.worldid import Verification


def http(method, url, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_local_page_relays_request_and_proof_to_the_gateway_and_rejects_strangers():
    calls = []

    def gw(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        return {"signal": "0xme"} if path == "/identity/request" else {"person": "0xp"}

    v = Verification(gw)
    try:
        base, token = v.url.split("/?t=")
        assert http("GET", f"{base}/?t=wrong")[0] == 403
        assert http("POST", f"{base}/result?t=wrong", {"x": 1})[0] == 403
        code, page = http("GET", v.url)
        assert code == 200 and token in page and "pollUntilCompletion" in page
        assert json.loads(http("GET", f"{base}/request?t={token}")[1]) == {"signal": "0xme"}
        assert http("POST", f"{base}/result?t={token}", {"responses": []})[0] == 200
        assert calls[-1] == ("POST", "/identity/register", {"responses": []}) and v.outcome == {"person": "0xp"}
    finally:
        v.close()


def test_the_page_server_only_listens_on_localhost():
    v = Verification(lambda *a, **k: {})
    try:
        assert v.server.server_address[0] == "127.0.0.1"
    finally:
        v.close()
