from __future__ import annotations

import subprocess
import sys

import httpx
import pytest

from tests.conftest import make_settings


async def test_healthz(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"]


async def test_config_is_public_and_describes_auth(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/config")
    assert r.status_code == 200
    body = r.json()
    assert body["api_base"] == "/api/v1"
    assert body["auth"]["mode"] == "dev"
    assert body["auth"]["dev_login"] is True


def test_import_has_no_side_effects() -> None:
    code = (
        "import sys, momentum; "
        "assert 'momentum.app' not in sys.modules; "
        "assert 'sqlalchemy.ext.asyncio' not in sys.modules; print('ok')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "ok"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"env": "production", "auth_mode": "dev", "secret_key": "x" * 40}, "not allowed"),
        ({"env": "production", "auth_mode": "easyauth", "secret_key": "short"}, "SECRET_KEY"),
        ({"base_path": "momentum"}, "must start with"),
    ],
)
def test_invalid_settings_fail_fast(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_settings(**overrides)


def test_base_path_is_normalized() -> None:
    assert make_settings(base_path="/momentum/").base_path == "/momentum"


async def test_unknown_error_is_problem_json(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "unauthenticated"
    assert r.json()["login_url"].startswith("/dev/login")
