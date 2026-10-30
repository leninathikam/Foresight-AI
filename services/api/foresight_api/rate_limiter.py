"""In-memory sliding window rate limiter for Foresight AI API."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


@dataclass
class RateLimitRule:
    max_requests: int
    window_s: float
    description: str


# Endpoint-specific rate limits per client IP
DEFAULT_RULES: dict[str, RateLimitRule] = {
    "agent_runs": RateLimitRule(max_requests=10, window_s=60.0, description="Agent runs (max 10/min)"),
    "model_check": RateLimitRule(max_requests=6, window_s=60.0, description="Model connectivity check (max 6/min)"),
    "futures": RateLimitRule(max_requests=20, window_s=60.0, description="Future simulation branches (max 20/min)"),
    "create_session": RateLimitRule(max_requests=15, window_s=3600.0, description="Session creation (max 15/hr)"),
    "general": RateLimitRule(max_requests=180, window_s=60.0, description="General API requests (max 180/min)"),
}


class SlidingWindowRateLimiter:
    def __init__(self, rules: dict[str, RateLimitRule] | None = None, enabled: bool = True) -> None:
        self.rules = rules or DEFAULT_RULES
        self.enabled = enabled
        self._history: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self._lock = asyncio.Lock()

    def _match_category(self, path: str, method: str) -> str:
        if method == "POST" and "/agent/runs" in path:
            return "agent_runs"
        if method == "POST" and path.startswith("/api/diagnostics/model-check"):
            return "model_check"
        if method == "POST" and "/futures" in path:
            return "futures"
        if method == "POST" and path == "/api/sessions":
            return "create_session"
        return "general"

    async def is_allowed(self, client_ip: str, path: str, method: str) -> tuple[bool, str | None, float]:
        if not self.enabled:
            return True, None, 0.0

        category = self._match_category(path, method)
        rule = self.rules.get(category, self.rules["general"])
        now = time.monotonic()
        cutoff = now - rule.window_s

        async with self._lock:
            history = self._history[client_ip][category]
            # Prune timestamps outside window
            history[:] = [t for t in history if t > cutoff]

            if len(history) >= rule.max_requests:
                oldest = history[0]
                retry_after = max(1.0, round(rule.window_s - (now - oldest), 1))
                return False, rule.description, retry_after

            history.append(now)
            return True, None, 0.0

    async def cleanup(self) -> None:
        now = time.monotonic()
        async with self._lock:
            for ip in list(self._history.keys()):
                for cat in list(self._history[ip].keys()):
                    rule = self.rules.get(cat, self.rules["general"])
                    self._history[ip][cat] = [t for t in self._history[ip][cat] if t > now - rule.window_s]
                    if not self._history[ip][cat]:
                        del self._history[ip][cat]
                if not self._history[ip]:
                    del self._history[ip]


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: SlidingWindowRateLimiter) -> None:
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.limiter.enabled:
            return await call_next(request)

        # Skip rate limiting for static / docs / health checks
        path = request.url.path
        if path in ("/api/health", "/docs", "/openapi.json", "/favicon.ico"):
            return await call_next(request)

        # Get client IP (support reverse-proxy headers if present)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif request.client:
            client_ip = request.client.host
        else:
            client_ip = "127.0.0.1"

        allowed, desc, retry_after = await self.limiter.is_allowed(client_ip, path, request.method)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {desc}. Please retry after {retry_after}s."},
                headers={"Retry-After": str(int(retry_after))},
            )

        return await call_next(request)
