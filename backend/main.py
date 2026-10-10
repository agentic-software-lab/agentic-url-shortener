from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="Agentic URL Shortener", version="1.0.0")


class ShortenRequest(BaseModel):
    url: HttpUrl


class UrlRecord(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime
    clicks: int = 0


URLS: Dict[str, UrlRecord] = {}


def generate_code(url: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()
    return digest[:8]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/urls", response_model=UrlRecord)
def create_short_url(payload: ShortenRequest) -> UrlRecord:
    original = str(payload.url)
    short_code = generate_code(original)

    if short_code not in URLS:
        URLS[short_code] = UrlRecord(
            short_code=short_code,
            original_url=original,
            created_at=datetime.now(timezone.utc),
            clicks=0,
        )

    return URLS[short_code]


@app.get("/r/{short_code}")
def redirect(short_code: str) -> RedirectResponse:
    record = URLS.get(short_code)
    if not record:
        raise HTTPException(status_code=404, detail="Short URL not found")

    record.clicks += 1
    return RedirectResponse(record.original_url, status_code=307)


@app.get("/urls/{short_code}/analytics")
def analytics(short_code: str) -> dict[str, object]:
    record = URLS.get(short_code)
    if not record:
        raise HTTPException(status_code=404, detail="Short URL not found")

    return {
        "short_code": record.short_code,
        "original_url": record.original_url,
        "created_at": record.created_at,
        "clicks": record.clicks,
    }
