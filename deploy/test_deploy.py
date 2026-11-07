import os
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

import pytest
import yaml

HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launch, create_secrets, attest, check_roles = (load(n) for n in ("launch", "create_secrets", "attest", "check_roles"))
RECEIPT = {"provider": "0x" + "AB" * 20, "trust_mode": "private", "tee_verified": True, "signer_matches_onchain": True}


def test_generated_secrets_are_private_separate_and_accepted_by_launch(tmp_path):
    directory = tmp_path / "secrets"
    create_secrets.create(directory)
    assert os.name == "nt" or directory.stat().st_mode & 0o777 == 0o700  # POSIX modes only
    for name in ("gateway", "verifier", "curator", "attestation"):
        assert os.name == "nt" or (directory / f"{name}.env").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        create_secrets.create(directory)
    verifier = (directory / "verifier.env").read_text()
    with pytest.raises(ValueError):  # blank API key: the operator must add it first
        launch.secret_environment("verifier", verifier)
    for service in ("verifier", "curator"):
        path = directory / f"{service}.env"
        path.write_text(path.read_text().replace("ZG_API_KEY=", "ZG_API_KEY=router-key"))
    gateway = directory / "gateway.env"  # Turnkey issues the parent-org key; the operator adds it
    with pytest.raises(ValueError):
        launch.secret_environment("gateway", gateway.read_text())
    gateway.write_text(gateway.read_text().replace("TURNKEY_API_PRIVATE_KEY=", "TURNKEY_API_PRIVATE_KEY=" + "7" * 64))
    with pytest.raises(ValueError):  # World RP key must also be supplied by the operator
        launch.secret_environment("gateway", gateway.read_text())
    gateway.write_text(gateway.read_text().replace("WORLD_RP_SIGNING_KEY=", "WORLD_RP_SIGNING_KEY=" + "8" * 64))
    storage = set()
    for service in launch.REQUIRED:
        text = (directory / f"{service}.env").read_text()
        values = launch.secret_environment(service, text)
        storage.add(values["ZG_STORAGE_PRIVATE_KEY"])
        assert ("MASTER_KEY" in values) == (service == "gateway")
        assert ("WORLD_RP_SIGNING_KEY" in values) == (service == "gateway")
    assert len(storage) == 3
    assert not any(value in (directory / "addresses.json").read_text() for value in storage)


@pytest.mark.parametrize("text", ["", "MASTER_KEY=" + "1" * 64, "LORE_VERIFIER_KEY=short\nZG_API_KEY=x\nZG_STORAGE_PRIVATE_KEY=" + "1" * 64])
def test_launch_refuses_foreign_or_malformed_secrets(text):
    with pytest.raises(ValueError):
        launch.secret_environment("verifier", text)
    with pytest.raises(ValueError):
        launch.secret_environment("unknown", text)


def test_gateway_accepts_optional_agent_pass_secret_only():
    values = {name: "1" * 64 for name in launch.REQUIRED["gateway"]}
    base = "\n".join(f"{k}={v}" for k, v in values.items())
    assert "WORLD_IDP_CLIENT_SECRET" not in launch.secret_environment("gateway", base)  # optional
    secret = "not-hex_client-secret.42"
    assert launch.secret_environment("gateway", base + f"\nWORLD_IDP_CLIENT_SECRET={secret}")["WORLD_IDP_CLIENT_SECRET"] == secret
    for bad in ("\nWORLD_IDP_CLIENT_SECRET=", f"\nWORLD_IDP_CLIENT_SECRET={secret}\nWORLD_IDP_CLIENT_SECRET={secret}"):
        with pytest.raises(ValueError):
            launch.secret_environment("gateway", base + bad)
    verifier = "\n".join(f"{k}={'1' * 64}" for k in launch.REQUIRED["verifier"])
    with pytest.raises(ValueError):  # only the gateway may hold it
        launch.secret_environment("verifier", verifier + f"\nWORLD_IDP_CLIENT_SECRET={secret}")


def test_compose_matches_launch_and_keeps_secrets_out_of_the_environment():
    compose = yaml.safe_load((HERE / "compose.yaml").read_text())
    assert set(compose["services"]) == set(launch.REQUIRED)
    for name, service in compose["services"].items():
        assert service["environment"]["LORE_SERVICE"] == name
        assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
        assert service["secrets"] == [{"source": f"{name}_env", "target": "lore.env"}]
        assert not set(service["environment"]) & set().union(*launch.REQUIRED.values(), *launch.OPTIONAL.values())
        assert service["environment"].get("LORE_STORAGE_CLI")
    assert compose["services"]["gateway"]["ports"][0].startswith("127.0.0.1:")
    assert "ports" not in compose["services"]["verifier"] and "ports" not in compose["services"]["curator"]
    assert compose["services"]["gateway"]["environment"]["WORLD_IDKIT_MODULE"] == (
        "${WORLD_IDKIT_MODULE:-https://cdn.jsdelivr.net/npm/@worldcoin/idkit-core@4.6.0/+esm}"
    )


@pytest.mark.parametrize("key", [None, "", "short", "g" * 64, "1" * 63, "1" * 65])
def test_gateway_refuses_missing_or_malformed_world_signing_key(key):
    values = {name: "1" * 64 for name in launch.REQUIRED["gateway"]}
    if key is None:
        del values["WORLD_RP_SIGNING_KEY"]
    else:
        values["WORLD_RP_SIGNING_KEY"] = key
    with pytest.raises(ValueError):
        launch.secret_environment("gateway", "\n".join(f"{name}={value}" for name, value in values.items()))


@pytest.mark.parametrize("service", ["verifier", "curator"])
def test_world_signing_key_is_rejected_by_other_services(service):
    values = {name: "1" * 64 for name in launch.REQUIRED[service]}
    values["WORLD_RP_SIGNING_KEY"] = "2" * 64
    with pytest.raises(ValueError):
        launch.secret_environment(service, "\n".join(f"{name}={value}" for name, value in values.items()))


def test_launch_passes_world_signing_key_from_secret_file_to_gateway(monkeypatch, capsys):
    values = {name: "1" * 64 for name in launch.REQUIRED["gateway"]}
    values["WORLD_RP_SIGNING_KEY"] = "0x" + "2" * 64
    monkeypatch.setenv("LORE_SERVICE", "gateway")
    # Register environment cleanup for every variable launch.main writes.
    for name in values:
        monkeypatch.setenv(name, "replaced-by-mounted-secret")
    monkeypatch.setattr(launch.Path, "read_text", lambda _: "\n".join(f"{n}={v}" for n, v in values.items()))
    executed = []
    monkeypatch.setattr(launch.os, "execvp", lambda program, argv: executed.append(
        (program, argv, os.environ["WORLD_RP_SIGNING_KEY"])))
    launch.main()
    assert executed == [("python", ["python", "-m", "gateway"], values["WORLD_RP_SIGNING_KEY"])]
    assert capsys.readouterr() == ("", "")


def test_receipt_roots_come_from_metadata_and_reports(tmp_path):
    path = tmp_path / "gateway.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE nodes (meta_json TEXT); CREATE TABLE topics (meta_json TEXT); CREATE TABLE submissions (report_hash TEXT);")
    db.execute("INSERT INTO nodes VALUES (?)", (json.dumps({"receipt": "0xnode"}),))
    db.execute("INSERT INTO nodes VALUES (NULL)")
    db.execute("INSERT INTO topics VALUES (?)", (json.dumps({"receipt": "0xtopic"}),))
    db.execute("INSERT INTO submissions VALUES ('0xreport')")
    db.commit()
    db.close()
    assert attest.receipt_roots(path, lambda root: {"receipts": ["0xverifier"]}) == ["0xnode", "0xtopic", "0xverifier"]


def test_attest_publishes_cli_output_per_provider(monkeypatch):
    published = []
    monkeypatch.setattr(attest.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="verified"))
    result = attest.attest([RECEIPT, RECEIPT], publish=lambda data: published.append(data) or "0xroot")
    assert result == [{"provider": RECEIPT["provider"].lower(), "storage_root": "0xroot"}]
    assert len(published) == 1 and b"verified" in published[0]


@pytest.mark.parametrize("bad", [{"tee_verified": False}, {"trust_mode": "basic"}, {"signer_matches_onchain": False}, {"provider": "nope"}])
def test_attest_refuses_unverified_receipts(bad):
    with pytest.raises(ValueError):
        attest.providers([{**RECEIPT, **bad}])


def test_attest_publishes_nothing_when_the_cli_fails(monkeypatch):
    monkeypatch.setattr(attest.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(RuntimeError):
        attest.attest([RECEIPT], publish=lambda data: pytest.fail("published"))


def test_role_check_reports_missing_roles_and_gas():
    class Reader:
        web3 = SimpleNamespace(eth=SimpleNamespace(get_balance=lambda address: {"0xb": 0}.get(address, 1) if address.startswith("0x") else 1 / 0))

        def call(self, contract, method, *args):
            return args[1] != "0xc" if method == "hasRole" else method

    good = check_roles.check(Reader(), {"gateway": "0xa", "verifier": "0xa", "curator": "0xa",
                                       "turnkey_delegated_public_key": "03ab"})  # as create_secrets writes it
    assert good["ready"] is True
    bad = check_roles.check(Reader(), {"gateway": "0xa", "verifier": "0xb", "curator": "0xc"})
    assert bad["ready"] is False and bad["roles"]["curator"] is False and bad["funded"]["verifier"] is False


def test_role_check_ignores_non_wallet_entries_like_the_turnkey_public_key():
    class Reader:
        web3 = SimpleNamespace(eth=SimpleNamespace(get_balance=lambda address: 1 if address.startswith("0x") else 1 / 0))

        def call(self, contract, method, *args):
            return True if method == "hasRole" else method

    report = check_roles.check(Reader(), {"gateway": "0xa", "verifier": "0xb", "curator": "0xc",
                                          "turnkey_delegated_public_key": "02" + "ab" * 32})
    assert report["ready"] is True and "turnkey_delegated_public_key" not in report["funded"]
def test_docker_builds_the_same_storage_cli_revision_as_build_py():
    dockerfile = (HERE / "Dockerfile").read_text()
    build = (HERE.parent / "shared" / "storage_cli" / "build.py").read_text()
    revision = re.search(r'REVISION = "([0-9a-f]{40})"', build).group(1)
    assert f"ARG STORAGE_CLI_REVISION={revision}\n" in dockerfile
