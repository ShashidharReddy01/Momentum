"""Development login: a signed cookie naming a seeded user. Never allowed in production."""

from __future__ import annotations

from urllib.parse import quote

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import Response

from momentum.auth.base import Principal
from momentum.core.settings import Settings

COOKIE = "momentum_dev_session"
MAX_AGE = 60 * 60 * 24 * 14


class DevSession:
    def __init__(self, settings: Settings) -> None:
        self._s = URLSafeTimedSerializer(settings.secret_key, salt="momentum-dev-session")
        self._path = settings.base_path or "/"

    def read(self, request: Request) -> dict[str, str] | None:
        raw = request.cookies.get(COOKIE)
        if not raw:
            return None
        try:
            data = self._s.loads(raw, max_age=MAX_AGE)
        except BadSignature:
            return None
        return data if isinstance(data, dict) else None

    def write(self, response: Response, *, user_id: str, email: str, name: str) -> None:
        token = self._s.dumps({"user_id": user_id, "email": email, "name": name})
        response.set_cookie(
            COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax", path=self._path
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(COOKIE, path=self._path)


class DevAuthProvider:
    name = "dev"

    def __init__(self, settings: Settings) -> None:
        if settings.env == "production":
            raise RuntimeError("dev auth is not allowed in production")
        self.settings = settings
        self.session = DevSession(settings)

    async def authenticate(self, request: Request) -> Principal | None:
        data = self.session.read(request)
        if not data:
            return None
        return Principal(
            provider="dev", subject=data["email"].lower(), email=data["email"], name=data["name"]
        )

    def login_url(self, return_to: str) -> str:
        return f"{self.settings.base_path}/dev/login?return_to={quote(return_to)}"

    def logout_url(self, return_to: str) -> str:
        return self.login_url(return_to)
