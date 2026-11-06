"""Gateway client for Lore's own agents. Signs in with the agent's role wallet."""

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

from gateway.auth import is_login_message
from jobs import NotReady


class Gateway:
    def __init__(self, url: str, key: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=url, timeout=60)
        self.acct = Account.from_key(key)
        self.token = None

    def _login(self):
        msg = self.http.post("/auth/nonce", json={"address": self.acct.address}).raise_for_status().json()["message"]
        if not is_login_message(msg, self.acct.address):
            raise RuntimeError("gateway sent an unexpected message to sign; refusing")
        sig = self.acct.sign_message(encode_defunct(text=msg)).signature.to_0x_hex()
        self.token = self.http.post(
            "/auth/verify", json={"address": self.acct.address, "message": msg, "signature": sig}
        ).raise_for_status().json()["token"]

    def get(self, path: str):
        """GET as this agent. A gateway that is down, restarting or not yet indexed is NotReady, not a failure."""
        try:
            for _ in range(2):  # one re-login if the token expired
                if not self.token:
                    self._login()
                r = self.http.get(path, headers={"Authorization": f"Bearer {self.token}"})
                if r.status_code != 401:
                    break
                self.token = None
        except httpx.TransportError as e:
            raise NotReady(f"gateway unreachable: {e}") from e
        if r.status_code == 404 or r.status_code >= 500:
            raise NotReady(f"gateway {r.status_code} for {path}")
        return r.raise_for_status().json()

    def plaintext(self, kind: str, iid: int) -> dict:
        return self.get(f"/internal/plaintext/{kind}/{iid}")

    def candidates(self, topic_id: int) -> dict:
        return self.get(f"/internal/candidates/{topic_id}")

    def topic(self, topic_id: int) -> dict:
        return self.get(f"/topics/{topic_id}")
