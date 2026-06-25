"""`/health` boots the app (real lifespan) and reports Redis up via fakeredis."""

from fastapi.testclient import TestClient

from backend.app import app


def test_health_reports_redis_ok() -> None:
    # TestClient runs the lifespan, so this exercises the real cache wiring.
    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["redis"] == "ok"  # fakeredis answers PING
    assert "tmdb_key_present" in body
