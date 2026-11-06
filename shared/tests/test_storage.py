from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from lore_shared.storage import CLI_VERSION, StorageClient, StorageError

KEY = "12" * 32
ROOT = "0x" + "ab" * 32


def test_encrypted_upload_and_proof_download_use_p2_config(monkeypatch):
    calls, paths = [], []

    def run(argv, **options):
        calls.append((argv, options))
        if argv[1] == "--lore-version":
            return SimpleNamespace(returncode=0, stdout=CLI_VERSION + "\n", stderr="")
        path = Path(argv[argv.index("--file") + 1])
        paths.append(path)
        if argv[1] == "upload":
            assert path.read_bytes() == b"encrypted-blob"
            assert path.stat().st_mode & 0o777 == 0o600
            assert "--key" not in argv and KEY not in " ".join(argv)
            assert options["input"] == KEY
            assert "--fast-mode=false" in argv
            return SimpleNamespace(returncode=0, stdout="", stderr=f'level=info msg="file uploaded, root = {ROOT}"\n')
        assert "--proof" in argv
        assert options["input"] == ""
        path.write_bytes(b"encrypted-blob")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("MASTER_KEY", "must-not-inherit")
    client = StorageClient(private_key=KEY)
    assert client.upload(b"encrypted-blob") == ROOT
    assert client.download(ROOT) == b"encrypted-blob"
    assert all("MASTER_KEY" not in options["env"] for _, options in calls)
    assert all(not path.exists() for path in paths)
    assert KEY not in repr(client)


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_failures_never_expose_raw_output_or_keys(monkeypatch, failure):
    def run(argv, **options):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=KEY)
        if failure == "missing":
            raise FileNotFoundError(KEY)
        return SimpleNamespace(returncode=1, stdout=KEY, stderr="private content")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(StorageError) as error:
        StorageClient(private_key=KEY).upload(b"blob")
    assert KEY not in str(error.value) and "private content" not in str(error.value)
    assert error.value.__suppress_context__ or error.value.__context__ is None


def test_unsupported_binary_and_ambiguous_upload_results_fail(monkeypatch):
    client = StorageClient(private_key=KEY)
    monkeypatch.setattr(client, "_run", lambda *args, **kwargs: "stock CLI")
    with pytest.raises(StorageError, match="unsupported"):
        client.upload(b"blob")
    monkeypatch.setattr(client, "_check_cli", lambda: None)
    for output in ("uploaded", f"root = {ROOT}", f"file uploaded, root = {ROOT}\nfile uploaded, root = {ROOT}"):
        monkeypatch.setattr(client, "_run", lambda *args, **kwargs: output)
        with pytest.raises(StorageError, match="exactly one"):
            client.upload(b"blob")


def test_limits_and_root_validation(monkeypatch):
    client = StorageClient(private_key=KEY, max_bytes=4)
    for data in (b"", b"12345", "text"):
        with pytest.raises(ValueError):
            client.upload(data)
    for root in ("invalid", ROOT + "1", "--help"):
        with pytest.raises(ValueError):
            client.download(root)
    with pytest.raises(ValueError):
        StorageClient(chain_id=31337)
    monkeypatch.setattr(client, "_check_cli", lambda: None)
    def download(args, **kwargs):
        Path(args[args.index("--file") + 1]).write_bytes(b"12345")
    monkeypatch.setattr(client, "_run", download)
    with pytest.raises(StorageError, match="size"):
        client.download(ROOT)
