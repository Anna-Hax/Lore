"""Gateway client for Lore's own agents (verifier, curator). Authenticates with the shared service secret."""

import httpx

from jobs import NotReady


class Gateway:
    def __init__(self, url: str, service_token: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=url, timeout=60)
        self.headers = {"Authorization": f"Bearer {service_token}"}

    def get(self, path: str):
        """GET as a Lore service. A gateway that is down, restarting or not yet indexed is NotReady, not a failure."""
        try:
            r = self.http.get(path, headers=self.headers)
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
        return self.get(f"/internal/topics/{topic_id}")
