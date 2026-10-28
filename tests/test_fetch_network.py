import json

import pytest
import requests

from ingest import fetch_network
from ingest.fetch_network import shrunk_too_far


def _response(status, payload=None):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(payload or {}).encode()
    return r


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(fetch_network.time, "sleep", lambda s: None)


def test_timeout_is_retried_then_succeeds(monkeypatch):
    calls = []

    def fake(method, url, **kw):
        calls.append(url)
        if len(calls) < 3:
            raise requests.Timeout("slow")
        return _response(200, {"accessToken": "t"})

    monkeypatch.setattr(fetch_network.requests, "request", fake)
    assert fetch_network.login("http://x", "a", "b") == "t"
    assert len(calls) == 3


def test_timeout_raised_after_last_retry(monkeypatch):
    def fake(method, url, **kw):
        raise requests.Timeout("slow")

    monkeypatch.setattr(fetch_network.requests, "request", fake)
    with pytest.raises(requests.Timeout):
        fetch_network.login("http://x", "a", "b")


def test_client_error_is_not_retried(monkeypatch):
    calls = []

    def fake(method, url, **kw):
        calls.append(url)
        return _response(401)

    monkeypatch.setattr(fetch_network.requests, "request", fake)
    with pytest.raises(requests.HTTPError):
        fetch_network.login("http://x", "a", "b")
    assert len(calls) == 1


def test_shrink_guard():
    assert not shrunk_too_far(852, 852)
    assert not shrunk_too_far(700, 852)      # ordinary churn
    assert shrunk_too_far(55, 852)           # one account missing
    assert not shrunk_too_far(10, 0)         # nothing saved yet


def _run_main(monkeypatch, tmp_path, outcomes, *argv):
    """outcomes: label -> member list, or an exception to raise for that account."""
    monkeypatch.setenv("CNP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CNP_NETWORK_API_BASE", "http://x")
    (tmp_path / "accounts.json").write_text(json.dumps([{"label": l} for l in outcomes]))

    def fake_fetch(base, label, data_dir):
        out = outcomes[label]
        if isinstance(out, Exception):
            raise out
        return {"label": label, "me": {"boutiqueCode": label}, "campaign": {"id": 1}, "members": out}

    monkeypatch.setattr(fetch_network, "fetch_account", fake_fetch)
    monkeypatch.setattr(fetch_network.sys, "argv", ["fetch_network", *argv])
    fetch_network.main()


def _members(n, start=0):
    return [{"userId": i, "depth": 1} for i in range(start, start + n)]


def test_failed_account_keeps_previous_file(monkeypatch, tmp_path):
    out = tmp_path / "downline_raw.json"
    out.write_text(json.dumps({"members": _members(10)}))
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, tmp_path, {"a": _members(3), "b": requests.Timeout("slow")})
    assert len(json.loads(out.read_text())["members"]) == 10


def test_allow_partial_writes_anyway(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, {"a": _members(3), "b": requests.Timeout("slow")}, "--allow-partial")
    assert len(json.loads((tmp_path / "downline_raw.json").read_text())["members"]) == 3


def test_all_accounts_ok_replaces_file(monkeypatch, tmp_path):
    (tmp_path / "downline_raw.json").write_text(json.dumps({"members": _members(10)}))
    _run_main(monkeypatch, tmp_path, {"a": _members(6), "b": _members(6, start=4)})
    assert len(json.loads((tmp_path / "downline_raw.json").read_text())["members"]) == 10
    assert not (tmp_path / "downline_raw.json.tmp").exists()
