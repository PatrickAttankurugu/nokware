import httpx
import pytest

from nokware.mcp_server import REPO, trigger_run_impl


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
