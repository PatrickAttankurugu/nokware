import httpx
import pytest

from nokware.mcp_server import REPO, trigger_run_impl, _ledger


def test_trigger_run_without_token_errors_cleanly(monkeypatch):
    monkeypatch.delenv("GH_DISPATCH_TOKEN", raising=False)
    out = trigger_run_impl("all")
    assert "GH_DISPATCH_TOKEN" in out  # clear error message, no exception


def test_trigger_run_dispatches_expected_request(monkeypatch):
    monkeypatch.setenv("GH_DISPATCH_TOKEN", "test-token")
    captured = {}

    class FakeResponse:
        status_code = 204
        text = ""

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    out = trigger_run_impl("africapep")

    assert out == "run dispatched"
    assert captured["url"] == (
        f"https://api.github.com/repos/{REPO}/actions/workflows/nightly.yml/dispatches"
    )
    assert captured["json"]["ref"] == "main"
    assert captured["json"]["inputs"] == {"suite": "africapep"}
    assert captured["headers"]["Authorization"] == "Bearer test-token"


def test_trigger_run_handles_connect_error_cleanly(monkeypatch):
    monkeypatch.setenv("GH_DISPATCH_TOKEN", "test-token")

    def fake_post_connect_error(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "post", fake_post_connect_error)

    out = trigger_run_impl("all")
    assert out.startswith("error:")
    assert "ConnectError" in out
    assert isinstance(out, str)


def test_ledger_raises_clear_error_on_missing_env(monkeypatch):
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        _ledger()
    assert "NEON_DATABASE_URL is not set" in str(exc_info.value)
    assert "docs/mcp.md" in str(exc_info.value)
