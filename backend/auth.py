import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuth2Client
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, BadTimeSignature, URLSafeTimedSerializer

try:
    from .database import get_db
except ImportError:
    from database import get_db

LICHESS_HOST = "https://lichess.org"
LICHESS_PROVIDER = "lichess"
LICHESS_USER_AGENT = (
    "lichess-woodpecker/0.1.0 "
    "(+https://github.com/lawang24/lichess-woodpecker)"
)
SESSION_COOKIE_NAME = "woodpecker_session"
AUTH_FLOW_COOKIE_NAME = "woodpecker_auth_flow"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
AUTH_FLOW_MAX_AGE_SECONDS = 10 * 60
REQUIRED_ENV_VARS = (
    "SESSION_SECRET",
    "APP_BASE_URL",
    "LICHESS_CLIENT_ID",
)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    account_endpoint: str
    scope: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _session_secret() -> str:
    return _require_env("SESSION_SECRET")


def _flow_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret(), salt="woodpecker-auth-flow")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _lichess_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": LICHESS_USER_AGENT,
    }


def _cookie_secure(request: Request) -> bool:
    app_base_url = os.environ.get("APP_BASE_URL", "").strip()
    if app_base_url:
        return app_base_url.startswith("https://")
    return request.url.scheme == "https"


def _session_expiry() -> datetime:
    return _now() + timedelta(seconds=SESSION_MAX_AGE_SECONDS)


def _lichess_client_id() -> str:
    return _require_env("LICHESS_CLIENT_ID")


def validate_auth_configuration() -> None:
    for name in REQUIRED_ENV_VARS:
        _require_env(name)


def get_provider(provider: str) -> ProviderConfig:
    if provider != LICHESS_PROVIDER:
        raise HTTPException(404, "Provider not found")

    return ProviderConfig(
        name=LICHESS_PROVIDER,
        client_id=_lichess_client_id(),
        authorization_endpoint=f"{LICHESS_HOST}/oauth",
        token_endpoint=f"{LICHESS_HOST}/api/token",
        account_endpoint=f"{LICHESS_HOST}/api/account",
    )


def get_redirect_uri(request: Request, provider: str) -> str:
    get_provider(provider)
    base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/api/auth/{provider}/callback"


def build_authorization_url(provider: str, request: Request) -> tuple[str, dict]:
    config = get_provider(provider)
    code_verifier = generate_token(48)
    redirect_uri = get_redirect_uri(request, provider)
    client = OAuth2Client(
        client_id=config.client_id,
        redirect_uri=redirect_uri,
        scope=config.scope,
        code_challenge_method="S256",
        token_endpoint_auth_method="none",
    )
    try:
        authorization_url, state = client.create_authorization_url(
            config.authorization_endpoint,
            code_verifier=code_verifier,
        )
    finally:
        client.close()
    return authorization_url, {
        "provider": provider,
        "state": state,
        "code_verifier": code_verifier,
    }


def set_auth_flow_cookie(response, request: Request, flow_payload: dict) -> None:
    response.set_cookie(
        AUTH_FLOW_COOKIE_NAME,
        _flow_serializer().dumps(flow_payload),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        max_age=AUTH_FLOW_MAX_AGE_SECONDS,
        path="/",
    )


def clear_auth_flow_cookie(response) -> None:
    response.delete_cookie(AUTH_FLOW_COOKIE_NAME, path="/")


def read_auth_flow(request: Request, provider: str) -> dict:
    get_provider(provider)
    signed_payload = request.cookies.get(AUTH_FLOW_COOKIE_NAME)
    if not signed_payload:
        raise HTTPException(400, "Missing auth flow cookie")

    try:
        payload = _flow_serializer().loads(
            signed_payload,
            max_age=AUTH_FLOW_MAX_AGE_SECONDS,
        )
    except BadTimeSignature as exc:
        raise HTTPException(400, "Expired auth flow") from exc
    except BadSignature as exc:
        raise HTTPException(400, "Invalid auth flow") from exc

    if payload.get("provider") != provider:
        raise HTTPException(400, "Provider mismatch")
    return payload


async def exchange_code_for_token(
    code: str,
    code_verifier: str,
    redirect_uri: str,
    request: Request,
) -> str:
    del request  # The request is part of the interface used in tests.

    config = get_provider(LICHESS_PROVIDER)
    client = AsyncOAuth2Client(
        client_id=config.client_id,
        redirect_uri=redirect_uri,
        code_challenge_method="S256",
        token_endpoint_auth_method="none",
    )
    try:
        token = await client.fetch_token(
            config.token_endpoint,
            grant_type="authorization_code",
            code=code,
            code_verifier=code_verifier,
        )
    except Exception as exc:
        raise HTTPException(502, "Provider token exchange failed") from exc
    finally:
        await client.aclose()

    access_token = token.get("access_token")
    if not access_token:
        raise HTTPException(502, "Provider token exchange failed")
    return access_token


async def fetch_lichess_account(access_token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{LICHESS_HOST}/api/account",
                headers=_lichess_headers(access_token),
            )
            if response.status_code == 429:
                raise HTTPException(
                    429,
                    "Lichess rate limit reached; wait at least one minute before retrying.",
                )
            response.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Failed to fetch Lichess account") from exc

    payload = response.json()
    provider_user_id = payload.get("id")
    provider_username = payload.get("username")
    if not provider_user_id or not provider_username:
        raise HTTPException(502, "Lichess account payload was incomplete")

    return {
        "id": provider_user_id,
        "username": provider_username,
    }


def upsert_user(provider: str, provider_user_id: str, provider_username: str):
    get_provider(provider)
    db = get_db()
    try:
        user = db.execute(
            """
            INSERT INTO users (provider, provider_user_id, provider_username)
            VALUES (%s, %s, %s)
            ON CONFLICT (provider, provider_user_id)
            DO UPDATE SET
                provider_username = EXCLUDED.provider_username,
                last_seen_at = CURRENT_TIMESTAMP
            RETURNING *
            """,
            (provider, provider_user_id, provider_username),
        ).fetchone()
        db.commit()
        return user
    finally:
        db.close()


def create_session(user_id: int) -> str:
    session_token = generate_token(48)
    db = get_db()
    try:
        db.execute(
            """
            INSERT INTO sessions (user_id, session_token_hash, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, _hash_token(session_token), _session_expiry()),
        )
        db.commit()
    finally:
        db.close()
    return session_token


def set_session_cookie(response, request: Request, session_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def get_current_user(request: Request):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None

    db = get_db()
    try:
        user = db.execute(
            """
            SELECT u.*
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.session_token_hash = %s
              AND s.revoked_at IS NULL
              AND s.expires_at > CURRENT_TIMESTAMP
            """,
            (_hash_token(session_token),),
        ).fetchone()
        if not user:
            return None

        db.execute(
            """
            UPDATE sessions
            SET last_seen_at = CURRENT_TIMESTAMP
            WHERE session_token_hash = %s
            """,
            (_hash_token(session_token),),
        )
        db.execute(
            """
            UPDATE users
            SET last_seen_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (user["id"],),
        )
        db.commit()
        return user
    finally:
        db.close()


def require_current_user(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


def revoke_session(session_token: str | None) -> None:
    if not session_token:
        return

    db = get_db()
    try:
        db.execute(
            """
            UPDATE sessions
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE session_token_hash = %s
              AND revoked_at IS NULL
            """,
            (_hash_token(session_token),),
        )
        db.commit()
    finally:
        db.close()
