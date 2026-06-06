import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx


class AuthError(Exception):
    pass


@dataclass
class OAuthToken:
    access_token: str
    token_type: str
    scope: str
    expires_in: int
    expires_at: float = field(init=False)

    def __post_init__(self):
        self.expires_at = time.time() + self.expires_in

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60


def check_credentials(base_url: str, client_id: str, client_secret: str) -> str | None:
    """Return a user-facing error message if credentials are clearly misconfigured, or None."""
    if not base_url or not base_url.strip():
        return (
            "FORMR_BASE_URL is not set. "
            "Create a .env file with:\n"
            "  FORMR_BASE_URL=http://localhost\n"
            "  FORMR_CLIENT_ID=your_32_hex_client_id\n"
            "  FORMR_CLIENT_SECRET=your_64_hex_client_secret\n"
            "\n"
            "Get API credentials at <base_url>/admin/account#api"
            " (requires admin >= 2, scopes: survey:read, run:read, data:read)"
        )
    if not client_id or not client_id.strip():
        return (
            "FORMR_CLIENT_ID is not set. "
            "Add it to .env — generate one at your formr instance's /admin/account#api"
        )
    if not client_secret or not client_secret.strip():
        return (
            "FORMR_CLIENT_SECRET is not set. "
            "Add it to .env — generate one at your formr instance's /admin/account#api"
        )
    return None


async def get_token(
    base_url: str,
    client_id: str,
    client_secret: str,
    http_client: httpx.AsyncClient | None = None,
) -> OAuthToken:
    err = check_credentials(base_url, client_id, client_secret)
    if err:
        raise AuthError(err)

    url = urljoin(base_url.rstrip("/") + "/", "api/oauth/access_token")
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }

    client = http_client or httpx.AsyncClient()
    try:
        resp = await client.post(url, data=data)
        if resp.status_code == 400:
            raise AuthError(
                "Authentication failed (400 Bad Request). "
                "The formr server rejected the credentials. "
                "Check that your FORMR_CLIENT_ID and FORMR_CLIENT_SECRET are correct "
                "and were generated at <base_url>/admin/account#api.\n"
                "Current values:\n"
                f"  FORMR_BASE_URL={base_url}\n"
                f"  FORMR_CLIENT_ID={client_id[:8]}...\n"
                f"  FORMR_CLIENT_SECRET={client_secret[:8]}..."
            )
        if resp.status_code == 401:
            raise AuthError(
                "Authentication failed (401 Unauthorized). "
                "Your FORMR_CLIENT_ID and FORMR_CLIENT_SECRET were rejected. "
                "Verify they are correct and have the required scopes "
                "(survey:read, run:read, data:read)."
            )
        resp.raise_for_status()
        body = resp.json()
        return OAuthToken(
            access_token=body["access_token"],
            token_type=body["token_type"],
            scope=body.get("scope", ""),
            expires_in=body["expires_in"],
        )
    except httpx.ConnectError:
        raise AuthError(
            f"Cannot connect to formr server at {base_url}.\n"
            "Make sure the server is running and reachable.\n"
            "If running locally, start it with your dev server.\n"
            "Check FORMR_BASE_URL in .env (default: http://localhost)."
        )
    finally:
        if http_client is None:
            await client.aclose()
