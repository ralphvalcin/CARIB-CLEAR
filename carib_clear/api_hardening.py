"""API hardening — rate limiting, error pages, graceful shutdown for CARIB-CLEAR."""

import os
import time
import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple sliding-window rate limiter for buildathon demo.

    Limits requests per IP per endpoint. Not a production-grade solution
    (use Redis-based in production) but prevents demo abuse.
    """

    def __init__(self, requests_per_minute: int = 30):
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Check if the request is within the rate limit."""
        now = time.time()
        window = now - 60  # 1-minute sliding window
        self._windows[key] = [t for t in self._windows[key] if t > window]
        self._windows[key].append(now)
        return len(self._windows[key]) <= self.rpm

    def remaining(self, key: str) -> int:
        """Remaining requests in this window."""
        now = time.time()
        window = now - 60
        self._windows[key] = [t for t in self._windows[key] if t > window]
        return max(0, self.rpm - len(self._windows[key]))


# Global rate limiter
limiter = RateLimiter(requests_per_minute=30)


def register_hardening(app) -> None:
    """Register rate limiting middleware, error handlers, and shutdown on a FastAPI app."""

    from fastapi import Request, HTTPException
    from fastapi.responses import JSONResponse

    # ─── Rate limiting middleware ─────────────────────────────────
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if os.getenv("CARIB_CLEAR_TRUSTED_PROXY") == "1":
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip() or client_ip

        # Exclude health/metrics/docs from rate limiting
        skip_paths = ("/health", "/metrics", "/docs", "/openapi.json", "/favicon.ico")
        if any(request.url.path.startswith(p) for p in skip_paths):
            response = await call_next(request)
            return response

        if not limiter.is_allowed(client_ip):
            remaining = limiter.remaining(client_ip)
            logger.warning(
                "[RateLimit] exceeded for %s %s from %s",
                request.method,
                request.url.path,
                client_ip,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests",
                    "message": f"Rate limit of {limiter.rpm} requests/minute exceeded",
                    "retry_after_seconds": 60,
                    "remaining": remaining,
                },
                headers={"Retry-After": "60", "X-RateLimit-Remaining": str(remaining)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(limiter.remaining(client_ip))
        return response

    # ─── Error handlers ──────────────────────────────────────────
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not found",
                "message": f"Endpoint {request.method} {request.url.path} does not exist",
                "hint": "See /docs for available endpoints",
            },
        )

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc):
        logger.error("500 on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": "An unexpected error occurred",
                "endpoint": f"{request.method} {request.url.path}",
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail if isinstance(exc.detail, str) else "Request error",
                "message": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                "endpoint": f"{request.method} {request.url.path}",
            },
        )

    # ─── Graceful shutdown ───────────────────────────────────────
    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("[API] Shutting down gracefully...")
        # Close database connection
        try:
            from carib_clear.db import get_db
            get_db().close()
            logger.info("[API] Database closed")
        except Exception as e:
            logger.warning("[API] DB close error: %s", e)
        # Clear caches
        try:
            import carib_clear.api as api_mod
            api_mod._loan_history.clear()
            api_mod._demo_cache.clear()
            logger.info("[API] Caches cleared")
        except Exception:
            pass
        logger.info("[API] Shutdown complete")

    logger.info("[Hardening] Rate limiting (%d rpm), error handlers, graceful shutdown registered", limiter.rpm)
