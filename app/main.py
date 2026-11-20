"""FastAPI entry point.

Run locally:  uvicorn app.main:app --host 0.0.0.0 --port 4000
Docs:         http://localhost:4000/docs
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.platforms import get_platforms
from app.schemas import ErrorResponse, PostingRequest, PostingResponse
from app.services.posting_service import USER_AGENT, PostingService

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx logs full request URLs at INFO; Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    platforms = get_platforms(settings)  # fails fast on a bad ENABLED_PLATFORMS value
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
    ) as client:
        app.state.posting_service = PostingService(settings, platforms, client)
        configured = [p.name for p in platforms if p.is_configured()]
        logger.info(
            "Platforms selected: %s | configured: %s",
            ", ".join(p.name for p in platforms),
            ", ".join(configured) or "none",
        )
        yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Publishes a short message (max 200 characters, exactly one CTA link) to multiple "
        "third-party platforms through their official APIs and reports the result per platform."
    ),
    lifespan=lifespan,
)


def get_posting_service(request: Request) -> PostingService:
    return request.app.state.posting_service


ServiceDep = Annotated[PostingService, Depends(get_posting_service)]


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = []
    for err in exc.errors():
        field = ".".join(str(part) for part in err.get("loc", ()) if part != "body") or "body"
        message = str(err.get("msg", "Invalid value")).replace("Value error, ", "")
        details.append({"field": field, "message": message})
    summary = "; ".join(d["message"] for d in details)
    logger.info("Validation failed: %s", summary)
    body = ErrorResponse(error={"code": "validation_error", "message": summary, "details": details})
    return JSONResponse(status_code=422, content=body.model_dump())


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Keep 404 / 405 etc. in the same JSON error format as everything else."""
    codes = {404: "not_found", 405: "method_not_allowed"}
    body = ErrorResponse(
        error={"code": codes.get(exc.status_code, "http_error"), "message": str(exc.detail)}
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(), headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    body = ErrorResponse(error={"code": "internal_error", "message": "Internal server error"})
    return JSONResponse(status_code=500, content=body.model_dump())


@app.post(
    "/posting",
    response_model=PostingResponse,
    responses={422: {"model": ErrorResponse, "description": "Invalid message or CTA link"}},
    summary="Publish a message to all configured platforms",
    tags=["Posting"],
)
async def create_posting(
    payload: PostingRequest,
    service: ServiceDep,
) -> PostingResponse:
    logger.info("Posting request received (%d chars)", len(payload.message))
    return await service.post_to_all(payload.message, payload.cta_link)


@app.get("/health", tags=["Health"], summary="Health check")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/platforms", tags=["Posting"], summary="List platforms and configuration status")
async def list_platforms(service: ServiceDep) -> dict:
    """Shows which platforms are selected and whether credentials are present (never the values)."""
    return {
        "platforms": [
            {"key": p.key, "name": p.name, "configured": p.is_configured()}
            for p in service.platforms
        ]
    }
