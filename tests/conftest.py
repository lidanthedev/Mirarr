import base64
import os

import pytest


os.environ.setdefault("AUTH_USERNAME", "admin")
os.environ.setdefault("AUTH_PASSWORD", "changeme")
os.environ.setdefault("TMDB_API_KEY", "test-tmdb-api-key")


@pytest.fixture(scope="session")
def auth_headers() -> dict[str, str]:
    token = base64.b64encode(
        f"{os.environ['AUTH_USERNAME']}:{os.environ['AUTH_PASSWORD']}".encode("utf-8")
    ).decode("ascii")
    return {"Authorization": f"Basic {token}"}
