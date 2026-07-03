"""Basic HTTP authentication middleware.

The app expects AUTH_USERNAME and AUTH_PASSWORD to be configured and
protects every request with HTTP Basic Auth.
"""

import base64
import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import get_settings


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces HTTP Basic Auth for every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = get_settings()

        if not self._credentials_configured(settings):
            return self._unauthorized()

        # Check for Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header is None:
            return self._unauthorized()

        # Parse Basic auth
        try:
            scheme, credentials = auth_header.split(" ", 1)
            if scheme.lower() != "basic":
                return self._unauthorized()

            decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except ValueError:
            return self._unauthorized()

        username_ok = secrets.compare_digest(
            username.encode("utf-8"),
            settings.auth_username.encode("utf-8"),
        )
        password_ok = secrets.compare_digest(
            password.encode("utf-8"),
            settings.auth_password.get_secret_value().encode("utf-8"),
        )

        if not (username_ok and password_ok):
            return self._unauthorized()

        return await call_next(request)

    @staticmethod
    def _credentials_configured(settings) -> bool:
        return bool(
            settings.auth_username and settings.auth_password.get_secret_value()
        )

    @staticmethod
    def _unauthorized() -> Response:
        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Mirrarr"'},
        )
