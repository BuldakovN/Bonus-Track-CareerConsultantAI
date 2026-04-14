from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from .config import config


class HttpClient:
    def __init__(self, base_url: str, headers: Optional[Dict[str, str]] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        default_headers = {"User-Agent": config.user_agent, "Accept": "application/json"}
        if headers:
            default_headers.update(headers)
        self.session.headers.update(default_headers)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = self.session.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response


class StepikClient(HttpClient):
    def __init__(self):
        headers: Dict[str, str] = {}
        access_token = config.stepik_access_token
        if not access_token and config.stepik_client_id and config.stepik_client_secret:
            # Получаем токен по client_credentials
            resp = requests.post(
                "https://stepik.org/oauth2/token/",
                data={
                    "grant_type": "client_credentials",
                    "client_id": config.stepik_client_id,
                    "client_secret": config.stepik_client_secret,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            access_token = data.get("access_token")

        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        super().__init__("https://stepik.org/api", headers=headers)

    def list_courses(self, page: int = 1, page_size: int = 50, language: str | None = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page": page, "page_size": page_size, "is_public": "true"}
        if language:
            params["language"] = language
        return self.get("courses", params=params).json()




