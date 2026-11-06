import json

from zg.providers import Providers, expected_signer

TEE, TARGET = "0x" + "11" * 20, "0x" + "22" * 20


def svc(**kw):
    return {"url": "https://p.example/", "verifiability": "TeeML", "additionalInfo": "",
            "teeSignerAddress": TEE, **kw}


def test_expected_signer_follows_target_separated():
    assert expected_signer(svc()) == TEE
    sep = json.dumps({"targetSeparated": True, "targetTeeAddress": TARGET})
    assert expected_signer(svc(additionalInfo=sep)).lower() == TARGET
    assert expected_signer(svc(additionalInfo="not json")) == TEE


def test_only_teeml_providers_are_accepted_and_lookups_are_cached(monkeypatch):
    p = Providers.__new__(Providers)
    p._cache, calls = {}, []
    monkeypatch.setattr(p, "service", lambda provider: calls.append(provider) or svc())
    assert p("0xP") == ("https://p.example", TEE) and p("0xP") == ("https://p.example", TEE) and calls == ["0xP"]
    monkeypatch.setattr(p, "service", lambda provider: svc(verifiability="TeeTLS"))
    try:
        p("0xQ")
        raise AssertionError("TeeTLS must be refused")
    except ValueError as e:
        assert "not TeeML" in str(e)
