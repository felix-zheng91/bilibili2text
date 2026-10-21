"""Password-based authentication for the public Web UI.

The Web UI is commonly exposed through Cloudflare.  A session cookie signed
with HMAC-SHA256 keeps the API closed to anonymous visitors while remaining
compatible with EventSource/SSE and plain ``<a download>`` links, both of which
cannot attach custom request headers.

Configuration is environment based so that it works the same for local runs
and for the Docker Compose deployment:

- ``B2T_AUTH_ENABLED``: explicit on/off switch.  When unset, authentication is
  enabled automatically as soon as a password (or password hash) is configured.
- ``B2T_AUTH_USERNAME``: login name, defaults to ``admin``.
- ``B2T_AUTH_PASSWORD``: plaintext password, hashed in memory at startup.
- ``B2T_AUTH_PASSWORD_HASH``: scrypt hash produced by ``python -m backend.auth
  hash``; takes precedence over ``B2T_AUTH_PASSWORD``.
- ``B2T_AUTH_SECRET``: optional signing secret.  When omitted, a random secret
  is generated once and persisted in the database directory.
- ``B2T_AUTH_SESSION_HOURS``: session lifetime, defaults to 168 hours (7 days).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

AUTH_ENABLED_ENV = "B2T_AUTH_ENABLED"
AUTH_USERNAME_ENV = "B2T_AUTH_USERNAME"
AUTH_PASSWORD_ENV = "B2T_AUTH_PASSWORD"
AUTH_PASSWORD_HASH_ENV = "B2T_AUTH_PASSWORD_HASH"
AUTH_SECRET_ENV = "B2T_AUTH_SECRET"
AUTH_SESSION_HOURS_ENV = "B2T_AUTH_SESSION_HOURS"

SESSION_COOKIE_NAME = "b2t_session"
SESSION_COOKIE_PATH = "/"
DEFAULT_USERNAME = "admin"
DEFAULT_SESSION_HOURS = 168
_SECRET_FILE_NAME = ".auth_secret"
_TRUTHY = {"1", "true", "yes", "on"}
_MAX_PASSWORD_LENGTH = 1024

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_PREFIX = "scrypt"

PUBLIC_PATHS = frozenset(
    {
        "/api/health",
        "/api/auth/session",
        "/api/auth/login",
        "/api/auth/logout",
    }
)

_manager_lock = threading.Lock()


class AuthConfigurationError(RuntimeError):
    """Raised when authentication is enabled without usable credentials."""


@dataclass(frozen=True)
class AuthSession:
    username: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    username: str
    password_hash: str
    secret: bytes
    session_ttl_seconds: int
    credential_version: str


@dataclass
class _AttemptState:
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class LoginRateLimiter:
    """Small in-memory limiter for login attempts.

    The deployment runs a single uvicorn worker, so process-local state is
    enough.  Behind Cloudflare the caller IP is read from ``CF-Connecting-IP``
    (see :func:`client_ip`).
    """

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: float = 300.0,
        lockout_seconds: float = 900.0,
    ) -> None:
        self.max_failures = max(1, max_failures)
        self.window_seconds = max(1.0, window_seconds)
        self.lockout_seconds = max(1.0, lockout_seconds)
        self._states: dict[str, _AttemptState] = {}
        self._lock = threading.Lock()
        self._checks = 0

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            self._prune_occasionally(now)
            state = self._states.get(key)
            if state is None:
                return 0
            if state.blocked_until > now:
                return max(1, math.ceil(state.blocked_until - now))
            self._prune_failures(state, now)
            if not state.failures:
                self._states.pop(key, None)
            return 0

    def register_failure(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(key, _AttemptState())
            self._prune_failures(state, now)
            state.failures.append(now)
            if len(state.failures) >= self.max_failures:
                state.failures.clear()
                state.blocked_until = now + self.lockout_seconds
                return max(1, math.ceil(self.lockout_seconds))
            return 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

    def _prune_failures(self, state: _AttemptState, now: float) -> None:
        cutoff = now - self.window_seconds
        while state.failures and state.failures[0] < cutoff:
            state.failures.popleft()

    def _prune_occasionally(self, now: float) -> None:
        self._checks += 1
        if self._checks % 256 != 0:
            return
        stale = [
            key
            for key, state in self._states.items()
            if state.blocked_until <= now and not state.failures
        ]
        for key in stale:
            self._states.pop(key, None)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    """Hash a password with scrypt and return an env-safe string."""

    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return (
        f"{_SCRYPT_PREFIX}:{_SCRYPT_N}:{_SCRYPT_R}:{_SCRYPT_P}:"
        f"{_base64url_encode(salt)}:{_base64url_encode(digest)}"
    )


def _decode_scrypt_hash(stored_hash: str) -> tuple[int, int, int, bytes, bytes]:
    prefix, n_raw, r_raw, p_raw, salt_raw, digest_raw = stored_hash.split(":")
    if prefix != _SCRYPT_PREFIX:
        raise ValueError("unsupported password hash prefix")
    n = int(n_raw)
    r = int(r_raw)
    p = int(p_raw)
    if not (2 <= n <= 2**20 and 1 <= r <= 32 and 1 <= p <= 16):
        raise ValueError("invalid scrypt parameters")
    salt = _base64url_decode(salt_raw)
    expected = _base64url_decode(digest_raw)
    if not salt or not expected:
        raise ValueError("empty password hash component")
    return n, r, p, salt, expected


def is_valid_password_hash(stored_hash: str) -> bool:
    try:
        _decode_scrypt_hash(stored_hash)
    except (ValueError, TypeError):
        return False
    return True


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a hash produced by :func:`hash_password`."""

    try:
        n, r, p, salt, expected = _decode_scrypt_hash(stored_hash)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _parse_enabled(raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise AuthConfigurationError(
        f"{AUTH_ENABLED_ENV} 取值无效：{raw!r}；请使用 1/0、true/false 或 on/off"
    )


def _session_hours() -> int:
    raw = os.environ.get(AUTH_SESSION_HOURS_ENV, "").strip()
    if not raw:
        return DEFAULT_SESSION_HOURS
    try:
        value = int(raw)
    except ValueError as exc:
        raise AuthConfigurationError(
            f"{AUTH_SESSION_HOURS_ENV} 必须是正整数（小时），当前值：{raw!r}"
        ) from exc
    if value < 1:
        raise AuthConfigurationError(
            f"{AUTH_SESSION_HOURS_ENV} 必须大于等于 1，当前值：{value}"
        )
    return value


def _database_dir() -> Path:
    try:
        from backend.settings import get_app_config

        return Path(get_app_config().download.db_dir)
    except Exception:  # noqa: BLE001 - fall back to the project default
        from backend import PROJECT_ROOT

        return PROJECT_ROOT / "db_data"


def _load_or_create_secret() -> bytes:
    env_secret = os.environ.get(AUTH_SECRET_ENV, "").strip()
    if env_secret:
        if len(env_secret) < 32:
            logger.warning(
                "%s 长度较短（%d），建议使用至少 32 个字符的随机字符串",
                AUTH_SECRET_ENV,
                len(env_secret),
            )
        return env_secret.encode("utf-8")

    path = _database_dir() / _SECRET_FILE_NAME
    try:
        if path.exists():
            secret = path.read_bytes().strip()
            if secret:
                return secret
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_bytes(48)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = path.read_bytes().strip()
            if existing:
                return existing
            path.write_bytes(secret)
            return secret
        with os.fdopen(fd, "wb") as handle:
            handle.write(secret)
        logger.info("已生成登录会话签名密钥：%s", path)
        return secret
    except OSError as exc:
        logger.warning(
            "无法持久化登录会话签名密钥（%s），将使用临时密钥；"
            "服务重启后所有登录会话会失效",
            exc,
        )
        return secrets.token_bytes(48)


def _load_config() -> AuthConfig:
    password = os.environ.get(AUTH_PASSWORD_ENV, "")
    password_hash = os.environ.get(AUTH_PASSWORD_HASH_ENV, "").strip()
    raw_enabled = os.environ.get(AUTH_ENABLED_ENV, "").strip()

    if password and not password_hash:
        if len(password) > _MAX_PASSWORD_LENGTH:
            raise AuthConfigurationError(
                f"{AUTH_PASSWORD_ENV} 过长（最多 {_MAX_PASSWORD_LENGTH} 个字符）"
            )
        password_hash = hash_password(password)

    if raw_enabled:
        enabled = _parse_enabled(raw_enabled)
    else:
        enabled = bool(password_hash)

    if not enabled:
        return AuthConfig(
            enabled=False,
            username="",
            password_hash="",
            secret=b"",
            session_ttl_seconds=0,
            credential_version="",
        )

    if not password_hash:
        raise AuthConfigurationError(
            f"已启用登录保护，但未配置 {AUTH_PASSWORD_ENV} 或 {AUTH_PASSWORD_HASH_ENV}"
        )
    if not is_valid_password_hash(password_hash):
        raise AuthConfigurationError(
            f"{AUTH_PASSWORD_HASH_ENV} 格式无效；请使用 "
            "`python -m backend.auth hash` 重新生成"
        )

    username = os.environ.get(AUTH_USERNAME_ENV, "").strip() or DEFAULT_USERNAME
    credential_source = password if password else password_hash
    credential_version = hashlib.sha256(credential_source.encode("utf-8")).hexdigest()[
        :16
    ]

    return AuthConfig(
        enabled=True,
        username=username,
        password_hash=password_hash,
        secret=_load_or_create_secret(),
        session_ttl_seconds=_session_hours() * 3600,
        credential_version=credential_version,
    )


class AuthManager:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self.rate_limiter = LoginRateLimiter()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def verify_credentials(self, username: str, password: str) -> bool:
        if not self.enabled:
            return True
        if len(password) > _MAX_PASSWORD_LENGTH:
            return False
        try:
            username_ok = hmac.compare_digest(
                username.encode("utf-8"), self.config.username.encode("utf-8")
            )
        except UnicodeEncodeError:
            username_ok = False
        password_ok = verify_password(password, self.config.password_hash)
        # Always run both checks so a wrong username is not faster than a
        # wrong password.
        return username_ok & password_ok

    def issue_session(self) -> tuple[str, datetime]:
        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(seconds=self.config.session_ttl_seconds)
        payload = {
            "v": 1,
            "sub": self.config.username,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "cv": self.config.credential_version,
        }
        body = _base64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = _base64url_encode(self._sign(body))
        return f"{body}.{signature}", expires_at

    def verify_session_token(self, token: str) -> AuthSession | None:
        if not self.enabled or not token:
            return None
        try:
            body, signature = token.split(".", 1)
        except ValueError:
            return None
        expected = _base64url_encode(self._sign(body))
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            payload = json.loads(_base64url_decode(body))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("v") != 1:
            return None
        if payload.get("sub") != self.config.username:
            return None
        if payload.get("cv") != self.config.credential_version:
            return None
        try:
            expires_ts = int(payload["exp"])
            issued_ts = int(payload["iat"])
        except (KeyError, TypeError, ValueError):
            return None
        now_ts = int(datetime.now(tz=UTC).timestamp())
        if expires_ts <= now_ts:
            return None
        return AuthSession(
            username=self.config.username,
            issued_at=datetime.fromtimestamp(issued_ts, tz=UTC),
            expires_at=datetime.fromtimestamp(expires_ts, tz=UTC),
        )

    def read_session(self, request: Request) -> AuthSession | None:
        token = request.cookies.get(SESSION_COOKIE_NAME, "")
        return self.verify_session_token(token)

    def _sign(self, body: str) -> bytes:
        return hmac.new(
            self.config.secret, body.encode("ascii"), hashlib.sha256
        ).digest()


_manager: AuthManager | None = None


def get_auth_manager() -> AuthManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = AuthManager(_load_config())
    return _manager


def reset_auth_manager() -> None:
    """Reset the cached manager (used by tests and after config changes)."""

    global _manager
    with _manager_lock:
        _manager = None


def client_ip(request: Request) -> str:
    """Best-effort client IP, preferring headers set by Cloudflare and nginx."""

    for header in ("cf-connecting-ip", "x-real-ip"):
        value = request.headers.get(header, "").strip()
        if value:
            return value
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[-1].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def request_is_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded_proto = (
        request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    )
    if forwarded_proto == "https":
        return True
    if '"https"' in request.headers.get("cf-visitor", ""):
        return True
    return request.headers.get("x-forwarded-ssl", "").strip().lower() == "on"


def is_public_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in PUBLIC_PATHS


async def auth_middleware(request: Request, call_next):
    manager = get_auth_manager()
    if not manager.enabled:
        return await call_next(request)
    if request.method == "OPTIONS" or is_public_path(request.url.path):
        return await call_next(request)
    session = manager.read_session(request)
    if session is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "未登录或登录已过期，请重新登录"},
            headers={"Cache-Control": "no-store"},
        )
    request.state.auth_session = session
    return await call_next(request)


def _hash_cli() -> int:
    password = getpass.getpass("Password: ")
    if not password:
        print("Password must not be empty.")
        return 1
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 1
    print(hash_password(password))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Web UI authentication helpers",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("hash", help="generate a B2T_AUTH_PASSWORD_HASH value")
    args = parser.parse_args(argv)
    if args.command == "hash":
        return _hash_cli()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
