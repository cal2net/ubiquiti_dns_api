from __future__ import annotations

from typing import Any


class UniFiError(Exception):
    """HTTP or API error from the UniFi Network integration API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        status_name: str | None = None,
        request_id: str | None = None,
        request_path: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.status_name = status_name
        self.request_id = request_id
        self.request_path = request_path
        self.payload = payload or {}

    @classmethod
    def from_response(cls, status_code: int, payload: Any, fallback: str) -> UniFiError:
        if not isinstance(payload, dict):
            return cls(fallback, status_code=status_code, payload={"raw": payload})
        return cls(
            str(payload.get("message") or fallback),
            status_code=payload.get("statusCode", status_code),
            code=payload.get("code"),
            status_name=payload.get("statusName"),
            request_id=payload.get("requestId"),
            request_path=payload.get("requestPath"),
            payload=payload,
        )


class ConfigurationError(ValueError):
    """Invalid client configuration."""
