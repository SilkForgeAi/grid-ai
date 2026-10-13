import httpx
import pytest

from grid.moderation import policy_reason


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    for name in ("GRID_POLICY_URL", "GRID_POLICY_TOKEN", "GRID_RESTRICTED"):
        monkeypatch.delenv(name, raising=False)


def test_restricted_mode_requires_policy_service(monkeypatch):
    monkeypatch.setenv("GRID_RESTRICTED", "1")
    assert policy_reason("hello", kind="task")


def test_trusted_mode_has_no_implicit_data_transfer():
    assert policy_reason("hello", kind="task") is None


@pytest.mark.parametrize("body", [{"decision": "deny"}, {}, {"decision": True}, [], {"decision": "unknown"}])
def test_only_explicit_allow_permits_execution(monkeypatch, body):
    monkeypatch.setenv("GRID_POLICY_URL", "http://127.0.0.1:8080/policy")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))
    assert policy_reason("a task", kind="task")


def test_context_and_auth_are_sent_only_to_configured_endpoint(monkeypatch):
    import json

    monkeypatch.setenv("GRID_POLICY_URL", "https://policy.example/evaluate")
    monkeypatch.setenv("GRID_POLICY_TOKEN", "synthetic-test-token")
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"decision": "allow"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    assert policy_reason("new task", kind="task", context=["previous task"]) is None
    assert json.loads(seen[0].content)["context"] == ["previous task"]
    assert seen[0].headers["Authorization"] == "Bearer synthetic-test-token"


def test_unavailable_service_fails_closed(monkeypatch):
    monkeypatch.setenv("GRID_POLICY_URL", "http://localhost:8080/policy")

    def unavailable(request):
        raise httpx.ConnectError("offline")

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(unavailable), **kw))
    assert policy_reason("task", kind="task")


def test_remote_http_and_url_credentials_are_rejected(monkeypatch):
    for endpoint in ("http://policy.example", "https://user:secret@policy.example"):
        monkeypatch.setenv("GRID_POLICY_URL", endpoint)
        assert policy_reason("task", kind="task")
