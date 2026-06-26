"""/api/graph endpoint: payload passthrough + domain-error → HTTP status mapping."""

from fastapi.testclient import TestClient

import backend.app as appmod
from backend import scraper
from backend.models import GraphPayload, Stats


def _payload() -> GraphPayload:
    return GraphPayload(
        username="x",
        generated_at="2026-01-01T00:00:00Z",
        stats=Stats(rated=1, avg_rating=4.0, clusters=1),
    )


def test_graph_endpoint_returns_payload(monkeypatch) -> None:
    async def fake_build(username, redis, http, *, refresh=False):
        return _payload()

    monkeypatch.setattr(appmod, "build_graph", fake_build)
    with TestClient(appmod.app) as client:
        resp = client.get("/api/graph/x")
    assert resp.status_code == 200
    assert resp.json()["username"] == "x"


def test_graph_endpoint_maps_user_not_found(monkeypatch) -> None:
    async def fake_build(username, redis, http, *, refresh=False):
        raise scraper.UserNotFoundError(username)

    monkeypatch.setattr(appmod, "build_graph", fake_build)
    with TestClient(appmod.app) as client:
        resp = client.get("/api/graph/nope")
    assert resp.status_code == 404


def test_graph_endpoint_maps_private(monkeypatch) -> None:
    async def fake_build(username, redis, http, *, refresh=False):
        raise scraper.PrivateProfileError(username)

    monkeypatch.setattr(appmod, "build_graph", fake_build)
    with TestClient(appmod.app) as client:
        resp = client.get("/api/graph/secret")
    assert resp.status_code == 403
