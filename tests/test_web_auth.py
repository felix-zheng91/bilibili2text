import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web-ui"))

from backend.auth import (
    AuthConfig,
    AuthConfigurationError,
    AuthManager,
    LoginRateLimiter,
    hash_password,
    reset_auth_manager,
    verify_password,
)
from backend.main import app

SECRET = b"test-secret-that-is-long-enough-for-hmac"


def _auth_config(*, ttl_seconds: int = 3600, credential_version: str = "v1"):
    return AuthConfig(
        enabled=True,
        username="admin",
        password_hash=hash_password("correct horse battery staple"),
        secret=SECRET,
        session_ttl_seconds=ttl_seconds,
        credential_version=credential_version,
    )


def test_password_hash_round_trip() -> None:
    stored = hash_password("s3cret-password")
    assert stored.startswith("scrypt:")
    assert "$" not in stored
    assert verify_password("s3cret-password", stored) is True
    assert verify_password("wrong-password", stored) is False
    assert verify_password("s3cret-password", "not-a-hash") is False


def test_session_token_round_trip_and_tampering() -> None:
    manager = AuthManager(_auth_config())
    token, expires_at = manager.issue_session()

    session = manager.verify_session_token(token)
    assert session is not None
    assert session.username == "admin"
    assert session.expires_at == expires_at.replace(microsecond=0)

    assert manager.verify_session_token(token + "x") is None
    body, signature = token.split(".", 1)
    tampered = body[:-1] + ("A" if body[-1] != "A" else "B")
    assert manager.verify_session_token(f"{tampered}.{signature}") is None
    assert manager.verify_session_token("garbage") is None


def test_session_token_expires_and_password_change_invalidates_it() -> None:
    expired_manager = AuthManager(_auth_config(ttl_seconds=-1))
    expired_token, _ = expired_manager.issue_session()
    assert expired_manager.verify_session_token(expired_token) is None

    manager = AuthManager(_auth_config(credential_version="v1"))
    token, _ = manager.issue_session()
    changed = AuthManager(_auth_config(credential_version="v2"))
    assert changed.verify_session_token(token) is None


def test_credentials_and_rate_limiter() -> None:
    manager = AuthManager(_auth_config())
    assert manager.verify_credentials("admin", "correct horse battery staple")
    assert not manager.verify_credentials("admin", "wrong")
    assert not manager.verify_credentials("root", "correct horse battery staple")

    limiter = LoginRateLimiter(
        max_failures=2,
        window_seconds=60,
        lockout_seconds=120,
    )
    assert limiter.retry_after("1.2.3.4") == 0
    assert limiter.register_failure("1.2.3.4") == 0
    assert limiter.retry_after("1.2.3.4") == 0
    assert limiter.register_failure("1.2.3.4") >= 1
    assert limiter.retry_after("1.2.3.4") >= 1
    limiter.reset("1.2.3.4")
    assert limiter.retry_after("1.2.3.4") == 0


def test_secret_is_persisted_when_env_is_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("B2T_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("B2T_AUTH_SECRET", raising=False)
    monkeypatch.delenv("B2T_AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("B2T_AUTH_PASSWORD", "another-test-password")
    monkeypatch.setattr("backend.auth._database_dir", lambda: tmp_path)
    reset_auth_manager()

    first = AuthManager(_config_from_env())
    reset_auth_manager()
    second = AuthManager(_config_from_env())

    secret_file = tmp_path / ".auth_secret"
    assert secret_file.exists()
    assert first.config.secret == second.config.secret
    assert secret_file.stat().st_mode & 0o777 == 0o600


def _config_from_env() -> AuthConfig:
    from backend.auth import _load_config

    return _load_config()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("B2T_AUTH_ENABLED", "1")
    monkeypatch.setenv("B2T_AUTH_USERNAME", "admin")
    monkeypatch.setenv("B2T_AUTH_PASSWORD", "test-login-password")
    monkeypatch.setenv("B2T_AUTH_SECRET", SECRET.decode())
    reset_auth_manager()
    yield TestClient(app)
    reset_auth_manager()


def test_api_requires_login_and_accepts_session_cookie(client) -> None:
    assert client.get("/api/health").status_code == 200

    anonymous = client.get("/api/runtime")
    assert anonymous.status_code == 401
    assert client.get("/api/auth/session").json()["authenticated"] is False

    wrong = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert wrong.status_code == 401

    success = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-login-password"},
    )
    assert success.status_code == 200
    assert success.json()["authenticated"] is True
    assert "b2t_session" in client.cookies

    assert client.get("/api/runtime").status_code == 200
    session = client.get("/api/auth/session").json()
    assert session["authenticated"] is True
    assert session["username"] == "admin"
    assert session["expires_at"]

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["authenticated"] is False
    assert client.get("/api/runtime").status_code == 401


def test_login_is_rate_limited(client) -> None:
    attempts = []
    for _ in range(5):
        attempts.append(
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong-password"},
            )
        )
    assert all(response.status_code == 401 for response in attempts)

    blocked = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-login-password"},
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_auth_disabled_keeps_api_open(monkeypatch) -> None:
    monkeypatch.setenv("B2T_AUTH_ENABLED", "0")
    monkeypatch.delenv("B2T_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("B2T_AUTH_PASSWORD_HASH", raising=False)
    reset_auth_manager()
    try:
        client = TestClient(app)
        session = client.get("/api/auth/session").json()
        assert session == {
            "auth_required": False,
            "authenticated": True,
            "username": None,
            "expires_at": None,
        }
        assert client.get("/api/runtime").status_code == 200
    finally:
        reset_auth_manager()


def test_auth_enabled_without_password_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("B2T_AUTH_ENABLED", "1")
    monkeypatch.delenv("B2T_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("B2T_AUTH_PASSWORD_HASH", raising=False)
    reset_auth_manager()
    try:
        with pytest.raises(AuthConfigurationError, match="未配置"):
            from backend.auth import _load_config

            _load_config()
    finally:
        reset_auth_manager()


def test_invalid_auth_configuration_fails_closed(monkeypatch) -> None:
    from backend.auth import _load_config

    monkeypatch.setenv("B2T_AUTH_ENABLED", "tru")
    monkeypatch.setenv("B2T_AUTH_PASSWORD", "some-password")
    reset_auth_manager()
    with pytest.raises(AuthConfigurationError, match="取值无效"):
        _load_config()

    monkeypatch.setenv("B2T_AUTH_ENABLED", "1")
    monkeypatch.delenv("B2T_AUTH_PASSWORD", raising=False)
    monkeypatch.setenv("B2T_AUTH_PASSWORD_HASH", "scrypt:bad")
    reset_auth_manager()
    with pytest.raises(AuthConfigurationError, match="格式无效"):
        _load_config()
    reset_auth_manager()


def test_request_is_secure_behind_cloudflare_proxy() -> None:
    from backend.auth import request_is_secure

    class FakeRequest:
        def __init__(self, headers, scheme="http"):
            self.headers = headers
            self.url = type("URL", (), {"scheme": scheme})()

    assert request_is_secure(FakeRequest({"cf-visitor": '{"scheme":"https"}'}))
    assert request_is_secure(FakeRequest({"x-forwarded-proto": "https"}))
    assert request_is_secure(FakeRequest({}, scheme="https"))
    assert not request_is_secure(FakeRequest({}))


def test_session_expiry_datetime_uses_utc() -> None:
    manager = AuthManager(_auth_config(ttl_seconds=60))
    token, expires_at = manager.issue_session()
    session = manager.verify_session_token(token)
    assert session is not None
    assert session.expires_at.tzinfo is not None
    assert session.expires_at.utcoffset() == timedelta(0)
    assert expires_at.tzinfo is not None
    assert expires_at > datetime.now(tz=UTC)
