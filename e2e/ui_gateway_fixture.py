"""Loopback-only browser fixture: real gateway/OAuth/MCP, fake chain and storage.

Started by test_ui.mjs when GATEWAY_PYTHON points to the agents Python environment.
Never use this demo-login fixture for a deployment.
"""
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from gateway.app import create_app  # noqa: E402
from tests.fakes import FakeChain, FakeContent, FakeStorage  # noqa: E402

if __name__ == "__main__":
    with TemporaryDirectory(prefix="lore-ui-fixture-") as directory, socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        app = create_app(str(Path(directory) / "fixture.db"), FakeChain(), FakeContent(), FakeStorage(),
                         public_url=f"http://127.0.0.1:{port}", service_token="offline-fixture-only",
                         demo_login=True, site_dir=str(ROOT / "site"))
        print(f"http://127.0.0.1:{port}", flush=True)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        server.run(sockets=[sock])
