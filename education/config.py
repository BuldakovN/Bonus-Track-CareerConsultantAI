from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EducationConfig:
    stepik_client_id: str | None = os.getenv("STEPIK_CLIENT_ID")
    stepik_client_secret: str | None = os.getenv("STEPIK_CLIENT_SECRET")
    stepik_access_token: str | None = os.getenv("STEPIK_ACCESS_TOKEN")

    user_agent: str = os.getenv("EDU_USER_AGENT", "itmo-hackathone-education/0.1")


config = EducationConfig()


