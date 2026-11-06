"""Run Lore's three services on this machine against the deployed testnet contracts (demo / development).

    python deploy/run_local.py            # gateway on http://127.0.0.1:8080 (MCP at /mcp, explorer at /app/)

Each service gets only its own secret file from deploy/secrets/ (made by create_secrets.py), like launch.py does in
Docker. State lives in deploy/state/. The gateway runs Lore's labelled demo login because World ID is not configured
locally (LORE_DEMO_LOGIN=1). Needs uv, and a built storage CLI (python shared/storage_cli/build.py).
Ctrl+C stops all three.
"""

import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SECRETS, STATE = ROOT / "deploy" / "secrets", ROOT / "deploy" / "state"
CLI = ROOT / "shared" / "storage_cli" / "bin" / ("lore-storage-client.exe" if os.name == "nt" else "lore-storage-client")
PORT = int(os.environ.get("LORE_PORT", 8080))
GATEWAY = f"http://127.0.0.1:{PORT}"


def secrets(service: str) -> dict:
    out = {}
    for line in (SECRETS / f"{service}.env").read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and value and not line.startswith("#"):
            out[name.strip()] = value.strip()
    return out


def common() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LORE_", "ZG_", "MASTER_KEY", "WM_SECRET"))}
    env.update(LORE_CHAIN_ID=os.environ.get("LORE_CHAIN_ID", "16602"), LORE_STORAGE_CLI=str(CLI), PYTHONUNBUFFERED="1",
               LORE_GATEWAY_URL=GATEWAY, ZG_MODEL=os.environ.get("ZG_MODEL", "glm-5.3"))
    return env


SERVICES = {
    "gateway": {"LORE_PORT": str(PORT), "LORE_DB": str(STATE / "gateway.sqlite3"), "LORE_PUBLIC_URL": GATEWAY,
                "LORE_DEMO_LOGIN": "1", "LORE_SITE_DIR": str(ROOT / "site")},
    "verifier": {"LORE_JOBS_DB": str(STATE / "verifier-jobs.sqlite3")},
    "curator": {"LORE_JOBS_DB": str(STATE / "curator-jobs.sqlite3")},
}


def pump(name: str, stream) -> None:
    for line in iter(stream.readline, ""):
        print(f"[{name}] {line}", end="", flush=True)


def main() -> None:
    if not CLI.is_file():
        raise SystemExit(f"build the storage CLI first: python shared/storage_cli/build.py --output {CLI}")
    STATE.mkdir(parents=True, exist_ok=True)
    procs = []
    for name, extra in SERVICES.items():
        env = {**common(), **secrets(name), **extra}
        cmd = ["uv", "run", "--quiet", "--project", str(ROOT / "agents"), "--python", "3.12", "python", "-m", name]
        p = subprocess.Popen(cmd, cwd=ROOT / "agents", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=pump, args=(name, p.stdout), daemon=True).start()
        procs.append((name, p))
        if name == "gateway":
            time.sleep(4)  # let the gateway bind before its clients start polling it
    print(f"Lore is starting: MCP {GATEWAY}/mcp · explorer {GATEWAY}/app/ · Ctrl+C to stop", flush=True)
    try:
        while all(p.poll() is None for _, p in procs):
            time.sleep(1)
        for name, p in procs:
            if p.poll() is not None:
                print(f"[{name}] exited with {p.returncode}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        sys.exit(0)


if __name__ == "__main__":
    main()
