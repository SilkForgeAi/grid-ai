from starlette.testclient import TestClient

from grid.policy_service import create_policy_app


def test_service_rejects_browser_origins_and_invalid_payloads(monkeypatch):
    async def should_not_run(*a):
        raise AssertionError("Invalid request reached classifier")

    monkeypatch.setattr("grid.policy_service.classify", should_not_run)
    client = TestClient(create_policy_app("synthetic"), base_url="http://localhost")
    assert (
        client.post("/evaluate", json={"text": "hello"}, headers={"Origin": "https://evil.example"}).status_code == 403
    )
    assert client.post("/evaluate", json=[]).status_code == 400
    assert client.post("/evaluate", content="invalid json").status_code == 400


def test_service_returns_independent_decision(monkeypatch):
    async def deny(payload, model):
        assert model == "synthetic"
        assert payload["text"] == "review me"
        return "deny"

    monkeypatch.setattr("grid.policy_service.classify", deny)
    client = TestClient(create_policy_app("synthetic"), base_url="http://localhost")
    assert client.post("/evaluate", json={"text": "review me"}).json() == {"decision": "deny"}
