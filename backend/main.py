from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl

app = FastAPI(
    title="Agentic Software Engineering System",
    version="1.0.0",
    description=(
        "A controlled-autonomy SDLC orchestration prototype demonstrating requirement analysis, "
        "engineering workflow execution, validation, governance, and release readiness using a "
        "URL shortener as the reference application."
    ),
)

# The demo UI runs separately on localhost:3000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get(
    "/health",
    summary="Health check",
    responses={200: {"description": "Service is healthy"}},
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/urls",
    response_model=UrlRecord,
    summary="Create a short URL",
    responses={
        200: {"description": "Short URL created or existing deterministic mapping returned"},
        422: {"description": "Invalid request or URL"},
        409: {"description": "Short-code collision; existing mapping preserved"},
    },
)
def create_short_url(payload: ShortenRequest) -> UrlRecord:
    original = str(payload.url)
    short_code = generate_code(original)

    if short_code in URLS and URLS[short_code].original_url != original:
        raise HTTPException(status_code=409, detail="Short-code collision; existing mapping preserved")

    if short_code not in URLS:
        URLS[short_code] = UrlRecord(
            short_code=short_code,
            original_url=original,
            created_at=datetime.now(timezone.utc),
            clicks=0,
        )

    return URLS[short_code]


@app.get(
    "/r/{short_code}",
    response_class=RedirectResponse,
    summary="Redirect to the original URL",
    description=(
        "Returns HTTP 307 with a Location header pointing to the original URL and increments "
        "the click counter. For interactive testing, open this endpoint directly in a browser tab. "
        "Swagger UI executes requests with browser fetch(), which may display 'TypeError: Load failed' "
        "when it follows a redirect to an external domain because of that destination's CORS policy. "
        "That browser-fetch error does not mean the redirect endpoint failed."
    ),
    responses={
        307: {
            "description": "Redirect to the original URL",
            "headers": {
                "Location": {
                    "description": "Original destination URL",
                    "schema": {"type": "string", "format": "uri"},
                }
            },
        },
        404: {"description": "Short URL not found"},
    },
)
def redirect(short_code: str) -> RedirectResponse:
    record = URLS.get(short_code)
    if not record:
        raise HTTPException(status_code=404, detail="Short URL not found")

    record.clicks += 1
    return RedirectResponse(record.original_url, status_code=307)


@app.get(
    "/urls/{short_code}/analytics",
    summary="Get short URL analytics",
    responses={
        200: {"description": "Analytics returned successfully"},
        404: {"description": "Short URL not found"},
    },
)
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
