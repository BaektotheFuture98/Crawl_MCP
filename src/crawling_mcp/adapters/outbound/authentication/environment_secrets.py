from __future__ import annotations

import os

from crawling_mcp.domain.errors import AuthenticationRequiredError
from crawling_mcp.domain.models import Credentials


class EnvironmentSecretProvider:
    def credentials(self, username_env: str, password_env: str) -> Credentials:
        username = os.getenv(username_env)
        password = os.getenv(password_env)
        if not username or not password:
            raise AuthenticationRequiredError(reason="credential_environment_missing")
        return Credentials(username=username, password=password)
