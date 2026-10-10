from fastapi.testclient import TestClient

from backend.main import URLS, app


client = TestClient(app)


def setup_function() -> None:
    URLS.clear()


def test_create_redirect_and_analytics() -> None:
    create = client.post("/urls", json={"url": "https://example.com/path"})
    assert create.status_code == 200
    short_code = create.json()["short_code"]

    redirect = client.get(f"/r/{short_code}", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com/path"

    analytics = client.get(f"/urls/{short_code}/analytics")
    assert analytics.status_code == 200
    assert analytics.json()["clicks"] == 1


def test_missing_short_code_returns_404() -> None:
    response = client.get("/r/not-found", follow_redirects=False)
    assert response.status_code == 404
