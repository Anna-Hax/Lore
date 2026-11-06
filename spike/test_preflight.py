import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("preflight", Path(__file__).with_name("preflight.py"))
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_reports_presence_without_secret_values(monkeypatch):
    monkeypatch.setenv("ZG_API_KEY", "private-value-not-for-output")
    monkeypatch.setenv("ZG_STORAGE_PRIVATE_KEY", "wallet-value-not-for-output")
    report = preflight.collect()
    encoded = json.dumps(report)
    assert report["environment_present"]["ZG_API_KEY"] is True
    assert "private-value-not-for-output" not in encoded
    assert "wallet-value-not-for-output" not in encoded
    assert report["live_checks_executed"] is False


def test_missing_credentials_cannot_be_ready(monkeypatch):
    monkeypatch.delenv("ZG_API_KEY", raising=False)
    assert preflight.ready(preflight.collect()) is False
