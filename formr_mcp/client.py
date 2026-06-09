from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin, quote

import httpx

from formr_mcp.utils import validate_run_name
from .auth import AuthError, OAuthToken, get_token


class FormrClientError(Exception):
    pass


class FormrClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.client_id = client_id
        self.client_secret = client_secret
        self._http = http_client or httpx.AsyncClient()
        self._token: OAuthToken | None = None
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> FormrClient:
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()

    async def _ensure_token(self) -> str:
        if self._token is None or self._token.is_expired:
            self._token = await get_token(
                self.base_url,
                self.client_id,
                self.client_secret,
                self._http,
            )
        return self._token.access_token

    async def request(
        self,
        method: str,
        path: str,
        *,
        retried: bool = False,
        **kwargs: Any,
    ) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        resp = await self._http.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 401 and not retried:
            self._token = None
            return await self.request(method, path, retried=True, **kwargs)

        if resp.status_code == 204:
            return None
        if not resp.is_success:
            body = resp.text[:500]
            raise FormrClientError(
                f"{method} {path} -> {resp.status_code}: {body}"
            )

        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            return resp.json()
        return resp.text

    async def get_surveys(self, name: str | None = None) -> list[dict]:
        params = {"name": name} if name else {}
        return await self.request("GET", "api/v1/surveys", params=params)

    async def get_survey(self, name: str, format: str = "json") -> Any:
        validate_run_name(name)
        return await self.request(
            "GET", f"api/v1/surveys/{quote(name, safe='')}", params={"format": format}
        )

    async def get_runs(self, name: str | None = None) -> list[dict]:
        params = {"name": name} if name else {}
        return await self.request("GET", "api/v1/runs", params=params)

    async def get_run(self, name: str) -> dict:
        validate_run_name(name)
        return await self.request("GET", f"api/v1/runs/{quote(name, safe='')}")

    async def get_run_structure(self, name: str) -> dict:
        validate_run_name(name)
        return await self.request("GET", f"api/v1/runs/{quote(name, safe='')}/structure")

    async def put_run_structure(self, name: str, structure: dict) -> dict:
        validate_run_name(name)
        return await self.request(
            "PUT", f"api/v1/runs/{quote(name, safe='')}/structure", json=structure
        )

    async def create_run(self, name: str) -> dict:
        validate_run_name(name)
        return await self.request("POST", f"api/v1/runs/{quote(name, safe='')}")

    async def patch_run(self, name: str, settings: dict) -> dict:
        validate_run_name(name)
        return await self.request("PATCH", f"api/v1/runs/{quote(name, safe='')}", json=settings)

    async def delete_run(self, name: str) -> None:
        validate_run_name(name)
        return await self.request("DELETE", f"api/v1/runs/{quote(name, safe='')}")

    async def get_user_me(self) -> dict:
        return await self.request("GET", "api/v1/user/me")
