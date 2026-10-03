"""Shared FastAPI dependencies: who is calling, and which sessions they may touch.

Authentication is Microsoft Entra ID. The browser signs in with MSAL and sends
`Authorization: Bearer <access token>`; API Gateway's JWT authorizer is the first gate, and
`get_user` below re-validates the token itself (signature, audience, issuer, expiry), so the
backend never trusts a header just because a request reached it.

When ENTRA_TENANT_ID / ENTRA_CLIENT_ID are not set (local development) auth is OFF and every
request is the one user "local".
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.config import (
    ALLOW_ANON,
    AUTH_ENABLED,
    ENTRA_CLIENT_ID,
    ENTRA_REQUIRED_SCOPE,
    ENTRA_TENANT_ID,
    USE_AWS_STORAGE,
)
from app.services.audit.audit_store import AuditSession, store
from app.services.common import request_context

log = logging.getLogger(__name__)

LOCAL_USER_ID = "local"


@dataclass(frozen=True)
class User:
    id: str  # Entra object id (`oid`): stable per user across apps in the tenant
    name: str = ""
    email: str = ""


_jwk_client: jwt.PyJWKClient | None = None
_jwk_lock = threading.Lock()


def _jwks() -> jwt.PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        with _jwk_lock:
            if _jwk_client is None:
                _jwk_client = jwt.PyJWKClient(
                    f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/discovery/v2.0/keys",
                    cache_keys=True,
                    lifespan=3600,
                )
    return _jwk_client


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def validate_token(token: str) -> dict:
    """Verify an Entra access token for this API and return its claims."""
    try:
        signing_key = _jwks().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            # An access token's `aud` is this API's client id (token version 2) or its
            # Application ID URI (version 1) -- accept both.
            audience=[ENTRA_CLIENT_ID, f"api://{ENTRA_CLIENT_ID}"],
            # Version 2 tokens are issued by login.microsoftonline.com/<tenant>/v2.0; version 1
            # tokens (an API registration whose requestedAccessTokenVersion is null/1) by
            # sts.windows.net/<tenant>/. Both are this tenant.
            issuer=[
                f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0",
                f"https://sts.windows.net/{ENTRA_TENANT_ID}/",
            ],
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Token expired") from exc
    except jwt.PyJWKClientConnectionError as exc:
        # Could not reach Microsoft for the signing keys: that is our outage, not a bad token.
        log.error("could not fetch Entra signing keys: %s", exc)
        raise HTTPException(status_code=503, detail="Sign-in service unavailable") from exc
    except jwt.PyJWTError as exc:
        log.info("token rejected: %s", exc)
        raise _unauthorized("Invalid token") from exc

    # Delegated user tokens carry `scp`; app-only (client-credential) tokens do not.
    if ENTRA_REQUIRED_SCOPE and ENTRA_REQUIRED_SCOPE not in str(claims.get("scp", "")).split():
        log.info("token rejected: missing required scope %s", ENTRA_REQUIRED_SCOPE)
        raise HTTPException(status_code=403, detail="Token is not authorised for this API")
    return claims


async def get_user(authorization: str | None = Header(default=None)) -> User:
    """The signed-in user. Use as `user: User = Depends(get_user)`.

    This is `async` on purpose: a ContextVar set inside a *sync* dependency (which FastAPI runs
    in a worker thread) would not be visible to the endpoint. Here it is set on the request's
    own task, and every threadpool call made for the request inherits it.
    """
    if not AUTH_ENABLED:
        if USE_AWS_STORAGE and not ALLOW_ANON:
            # Fail closed: shared storage plus no sign-in would make every caller one user.
            log.error("ENTRA_TENANT_ID / ENTRA_CLIENT_ID are not set but AWS storage is on")
            raise HTTPException(
                status_code=503,
                detail="Authentication is not configured on the server (set ENTRA_TENANT_ID and ENTRA_CLIENT_ID).",
            )
        user = User(id=LOCAL_USER_ID, name="Local user")
    else:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise _unauthorized("Missing bearer token")
        # Validation may fetch the signing keys over the network (cached after the first), so
        # keep it off the event loop.
        claims = await run_in_threadpool(validate_token, authorization[7:].strip())
        oid = claims.get("oid") or claims.get("sub")
        if not oid:
            raise _unauthorized("Token has no user id")
        user = User(
            id=str(oid),
            name=str(claims.get("name", "")),
            email=str(claims.get("preferred_username") or claims.get("email") or ""),
        )
    request_context.current_user_id.set(user.id)
    return user


def load_owned_session(session_id: str, user: User) -> AuditSession:
    """The session if it exists AND belongs to `user`; otherwise 404. A session owned by
    someone else is reported as "not found" so ids cannot be probed."""
    session = store.get(session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    request_context.current_session_id.set(session_id)
    return session


def require_owned(session_id: str, user: User) -> None:
    """Ownership check for routes that only use the session id (planner, brief) and never
    load the session itself. 404 if missing or not the user's."""
    owner = store.owner_of(session_id)
    if owner is None or owner != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    request_context.current_session_id.set(session_id)
