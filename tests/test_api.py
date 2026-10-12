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


def test_hash_collision_preserves_mapping_and_duplicate_behavior(monkeypatch):
    monkeypatch.setattr('backend.main.generate_code', lambda url: 'collision')
    original = client.post('/urls', json={'url': 'https://example.com/first'})
    assert original.status_code == 200
    code = original.json()['short_code']
    conflicting = client.post('/urls', json={'url': 'https://example.com/second'})
    assert conflicting.status_code == 409
    redirect = client.get('/r/' + code, follow_redirects=False)
    assert redirect.headers['location'] == 'https://example.com/first'
    duplicate = client.post('/urls', json={'url': 'https://example.com/first'})
    assert duplicate.status_code == 200
    assert duplicate.json()['short_code'] == code
    assert duplicate.json()['clicks'] == 1
