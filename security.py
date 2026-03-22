from __future__ import annotations

import asyncio
import ipaddress
import time
from collections import defaultdict, deque
from collections.abc import Iterable
from urllib.parse import urlparse


class RateLimitExceededError(RuntimeError):
    pass


class TaskSubmissionValidationError(ValueError):
    pass


def validate_image_url(image_url: str, *, allow_local_inputs: bool) -> str:
    normalized = image_url.strip()
    if not normalized:
        raise TaskSubmissionValidationError("image_url is required")
    if urlparse(normalized).scheme == "upload":
        return normalized
    if allow_local_inputs:
        return normalized
    _parse_http_url(normalized, field_name="image_url")
    return normalized


def validate_callback_url(
    callback_url: str | None,
    *,
    allowed_domains: Iterable[str],
) -> str | None:
    if callback_url is None:
        return None

    normalized = callback_url.strip()
    if not normalized:
        return None

    parsed = _parse_http_url(normalized, field_name="callback_url")
    host = (parsed.hostname or "").lower()
    normalized_allowed_domains = tuple(
        domain.strip().lower().strip(".")
        for domain in allowed_domains
        if domain and domain.strip()
    )
    if normalized_allowed_domains and not any(
        _host_matches_allowed_domain(host, allowed_domain)
        for allowed_domain in normalized_allowed_domains
    ):
        raise TaskSubmissionValidationError(
            "callback_url host is not allowed by ALLOWED_CALLBACK_DOMAINS"
        )
    return normalized


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False

    normalized = host.partition("%")[0].strip().lower()
    if normalized == "localhost":
        return True

    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class TokenRateLimiter:
    def __init__(
        self,
        *,
        max_concurrent: int,
        max_requests_per_hour: int,
    ) -> None:
        self._max_concurrent = max(max_concurrent, 1)
        self._max_requests_per_hour = max(max_requests_per_hour, 1)
        self._request_timestamps: dict[str, deque[float]] = defaultdict(deque)
        self._active_tasks_by_token: dict[str, set[str]] = defaultdict(set)
        self._task_owner_by_id: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def max_requests_per_hour(self) -> int:
        return self._max_requests_per_hour

    async def update_limits(
        self,
        *,
        max_concurrent: int | None = None,
        max_requests_per_hour: int | None = None,
    ) -> None:
        async with self._lock:
            if max_concurrent is not None:
                self._max_concurrent = max(int(max_concurrent), 1)
            if max_requests_per_hour is not None:
                self._max_requests_per_hour = max(int(max_requests_per_hour), 1)

    async def record_request(self, token: str) -> None:
        async with self._lock:
            timestamps = self._request_timestamps[token]
            cutoff = time.monotonic() - 3600
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._max_requests_per_hour:
                raise RateLimitExceededError(
                    f"rate limit exceeded: max {self._max_requests_per_hour} task requests per hour"
                )
            timestamps.append(time.monotonic())

    async def check_concurrent_tasks(self, token: str) -> None:
        async with self._lock:
            if len(self._active_tasks_by_token[token]) >= self._max_concurrent:
                raise RateLimitExceededError(
                    f"rate limit exceeded: max {self._max_concurrent} concurrent tasks"
                )

    async def register_task(self, token: str, task_id: str) -> None:
        async with self._lock:
            self._active_tasks_by_token[token].add(task_id)
            self._task_owner_by_id[task_id] = token

    async def release_task(self, task_id: str) -> None:
        async with self._lock:
            token = self._task_owner_by_id.pop(task_id, None)
            if token is None:
                return
            active_tasks = self._active_tasks_by_token.get(token)
            if active_tasks is None:
                return
            active_tasks.discard(task_id)
            if not active_tasks:
                self._active_tasks_by_token.pop(token, None)


def _parse_http_url(value: str, *, field_name: str):
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise TaskSubmissionValidationError(f"{field_name} must use http:// or https://")
    if not parsed.hostname:
        raise TaskSubmissionValidationError(f"{field_name} must include a valid host")
    return parsed


def _host_matches_allowed_domain(host: str, allowed_domain: str) -> bool:
    if host == allowed_domain:
        return True
    return host.endswith(f".{allowed_domain}")
