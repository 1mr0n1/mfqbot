"""Thin HTTP client for our backend. The bot never talks to OpenRouter directly."""
import os

import httpx


class BackendError(Exception):
    pass


class BackendClient:
    def __init__(self, base_url: str | None = None):
        self._http = httpx.AsyncClient(base_url=base_url or os.environ["BACKEND_URL"], timeout=150)

    async def _request(self, method: str, path: str, **kwargs):
        try:
            resp = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise BackendError("Backend is unreachable.") from e
        if resp.is_error:
            raise BackendError(resp.json().get("detail", "Backend error."))
        return resp.json()

    async def list_models(self) -> list[dict]:
        return await self._request("GET", "/models")

    async def get_model(self, user_id: int) -> str:
        return (await self._request("GET", f"/users/{user_id}/model"))["model"]

    async def set_model(self, user_id: int, model: str) -> str:
        return (await self._request("PUT", f"/users/{user_id}/model", json={"model": model}))["model"]

    async def reset(self, user_id: int) -> None:
        await self._request("DELETE", f"/users/{user_id}/history")

    async def chat(self, user_id: int, message: str) -> str:
        data = await self._request("POST", "/chat", json={"user_id": str(user_id), "message": message})
        return data["reply"]

    async def close(self):
        await self._http.aclose()
