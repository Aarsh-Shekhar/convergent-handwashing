"""Lightweight LAN authentication: a shared bearer token from the environment.

* ``CONVERGENT_API_TOKEN`` must be set for any write endpoint to work; with it empty the
  backend refuses writes (fail closed) instead of exposing unauthenticated writes.
* Reads are allowed without a token by default on the development LAN
  (``CONVERGENT_ALLOW_UNAUTHENTICATED_READS=false`` to require it everywhere).
* The token is compared in constant time. This is **not** a production child-data access
  control model; docs/API.md lists what is required before real deployment.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from convergent.common.config import Settings

_bearer = HTTPBearer(auto_error=False)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _token_ok(provided: str | None, expected: str) -> bool:
    return bool(expected) and provided is not None and secrets.compare_digest(provided, expected)


def require_write(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    settings = _settings(request)
    if not settings.api_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="write endpoints disabled: CONVERGENT_API_TOKEN is not configured")
    if not _token_ok(creds.credentials if creds else None, settings.api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})


def require_read(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    settings = _settings(request)
    if settings.allow_unauthenticated_reads:
        return
    if not _token_ok(creds.credentials if creds else None, settings.api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})


def ws_token_ok(settings: Settings, token: str | None) -> bool:
    return _token_ok(token, settings.api_token)
