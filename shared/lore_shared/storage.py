"""0G Storage through the pinned CLI; upload ciphertext or public JSON only.

Keys go through stdin to our small launcher, never subprocess argv or logs.
Downloads always enable the official CLI's Merkle-proof verification.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .network import get_network

CLI_VERSION = "lore-storage-cli/bb5675461a96b654d3015c5522666ee8101cf810"
_ROOT = re.compile(r"0x[0-9a-fA-F]{64}")
_UPLOAD_ROOT = re.compile(r"file uploaded, root = (0x[0-9a-fA-F]{64})(?![0-9a-fA-F])")


class StorageError(RuntimeError):
    """Sanitized failure; raw subprocess output is intentionally not exposed."""


@dataclass
class StorageClient:
    cli: str = "lore-storage-client"
    chain_id: int = 16602  # Storage uses a real 0G network even with Anvil contracts.
    private_key: str | None = field(default=None, repr=False)
    timeout: float = 180
    max_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        if self.chain_id != 16602:
            raise ValueError("v1 storage writes are restricted to 0G testnet 16602")
        if self.timeout <= 0 or self.max_bytes <= 0:
            raise ValueError("storage limits must be positive")

    def _run(self, args: list[str], *, stdin: str = "") -> str:
        # Do not inherit gateway/role/Compute secrets into the storage process.
        names = ["PATH", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"]
        if os.name == "nt":  # go-ethereum panics without a home/profile dir on Windows; these hold no secrets
            names += ["SYSTEMROOT", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"]
        environment = {name: os.environ[name] for name in names if name in os.environ}
        try:
            result = subprocess.run(
                [self.cli, *args], input=stdin, text=True, capture_output=True,
                timeout=self.timeout, check=False, env=environment,
            )
        except (OSError, subprocess.SubprocessError):
            raise StorageError("storage CLI failed or timed out; no automatic upload retry") from None
        if result.returncode:
            raise StorageError("storage CLI returned an error; inspect a sanitized operator diagnostic")
        return result.stdout + result.stderr

    def _check_cli(self) -> None:
        if self._run(["--lore-version"]).strip() != CLI_VERSION:
            raise StorageError("unsupported storage CLI; build the pinned stdin-key launcher")

    def upload(self, data: bytes) -> str:
        if not isinstance(data, bytes) or not 0 < len(data) <= self.max_bytes:
            raise ValueError("upload requires nonempty bytes within the configured size limit")
        key = self.private_key or os.environ.get("ZG_STORAGE_PRIVATE_KEY", "")
        if not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", key):
            raise ValueError("ZG_STORAGE_PRIVATE_KEY must be a 32-byte hex key")
        self._check_cli()
        network = get_network(self.chain_id)
        with tempfile.TemporaryDirectory(prefix="lore-upload-") as directory:
            path = Path(directory) / "blob"
            path.write_bytes(data)
            path.chmod(0o600)
            output = self._run([
                "upload", "--url", network.rpc_url, "--indexer", network.storage_indexer,
                "--file", str(path), "--fast-mode=false", "--log-color-disabled",
            ], stdin=key)
        roots = _UPLOAD_ROOT.findall(output)
        if len(roots) != 1:
            raise StorageError("upload did not return exactly one storage root; check before retrying")
        return roots[0].lower()

    def download(self, root: str) -> bytes:
        if not isinstance(root, str) or not _ROOT.fullmatch(root):
            raise ValueError("storage root must be a 0x-prefixed bytes32")
        self._check_cli()
        network = get_network(self.chain_id)
        with tempfile.TemporaryDirectory(prefix="lore-download-") as directory:
            path = Path(directory) / "blob"
            self._run([
                "download", "--indexer", network.storage_indexer, "--root", root.lower(),
                "--file", str(path), "--proof", "--log-color-disabled",
            ])
            try:
                with path.open("rb") as stream:
                    data = stream.read(self.max_bytes + 1)
            except OSError:
                raise StorageError("storage download did not produce a readable file") from None
            if len(data) > self.max_bytes:
                raise StorageError("storage download exceeds the configured size limit")
            return data


def _default_client() -> StorageClient:
    return StorageClient(cli=os.environ.get("LORE_STORAGE_CLI", "lore-storage-client"))


def upload(data: bytes) -> str:
    return _default_client().upload(data)


def download(root: str) -> bytes:
    return _default_client().download(root)
