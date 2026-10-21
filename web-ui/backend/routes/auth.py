"""Login, logout and session endpoints."""

import logging
from datetime import UTC

from fastapi import APIRouter, HTTPException, Request, Response

from backend.auth import (
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
    client_ip,
    get_auth_manager,
    request_is_secure,
)
from backend.schemas import AuthLoginRequest, AuthSessionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _session_response(
    *,
    auth_required: bool,
    authenticated: bool,
    username: str | None = None,
    expires_at: str | None = None,
) -> AuthSessionResponse:
    return AuthSessionResponse(
        auth_required=auth_required,
        authenticated=authenticated,
        username=username,
        expires_at=expires_at,
    )


@router.get("/session", response_model=AuthSessionResponse)
def get_session(request: Request, response: Response) -> AuthSessionResponse:
    _no_store(response)
    manager = get_auth_manager()
    if not manager.enabled:
        return _session_response(auth_required=False, authenticated=True)

    session = manager.read_session(request)
    if session is None:
        return _session_response(auth_required=True, authenticated=False)
    return _session_response(
        auth_required=True,
        authenticated=True,
        username=session.username,
        expires_at=session.expires_at.astimezone(UTC).isoformat(),
    )


@router.post("/login", response_model=AuthSessionResponse)
def login(
    payload: AuthLoginRequest,
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    _no_store(response)
    manager = get_auth_manager()
    if not manager.enabled:
        return _session_response(auth_required=False, authenticated=True)

    ip = client_ip(request)
    retry_after = manager.rate_limiter.retry_after(ip)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=f"登录尝试次数过多，请在 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )

    username = payload.username.strip()
    if not manager.verify_credentials(username, payload.password):
        manager.rate_limiter.register_failure(ip)
        logger.warning("登录失败：ip=%s username=%r", ip, username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    manager.rate_limiter.reset(ip)
    token, expires_at = manager.issue_session()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=manager.config.session_ttl_seconds,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=request_is_secure(request),
    )
    logger.info("登录成功：ip=%s username=%r", ip, manager.config.username)
    return _session_response(
        auth_required=True,
        authenticated=True,
        username=manager.config.username,
        expires_at=expires_at.astimezone(UTC).isoformat(),
    )


@router.post("/logout", response_model=AuthSessionResponse)
def logout(request: Request, response: Response) -> AuthSessionResponse:
    _no_store(response)
    manager = get_auth_manager()
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=request_is_secure(request),
    )
    if not manager.enabled:
        return _session_response(auth_required=False, authenticated=True)
    return _session_response(auth_required=True, authenticated=False)
