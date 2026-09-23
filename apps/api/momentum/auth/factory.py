from __future__ import annotations

from starlette.requests import Request

from momentum.auth.base import AuthProvider, HostPrincipalResolver, Principal
from momentum.core.settings import Settings


class HostAuthProvider:
    """Embedded mode: the host application authenticates and hands us a Principal."""

    name = "host"

    def __init__(self, settings: Settings, resolver: HostPrincipalResolver) -> None:
        self.settings = settings
        self._resolver = resolver

    async def authenticate(self, request: Request) -> Principal | None:
        return await self._resolver(request)

    def login_url(self, return_to: str) -> str:
        return return_to

    def logout_url(self, return_to: str) -> str:
        return return_to


def build_auth_provider(
    settings: Settings, host_resolver: HostPrincipalResolver | None = None
) -> AuthProvider:
    match settings.auth_mode:
        case "dev":
            from momentum.auth.dev import DevAuthProvider

            return DevAuthProvider(settings)
        case "easyauth-sim":
            from momentum.auth.easyauth_sim import EasyAuthSimProvider

            return EasyAuthSimProvider(settings)
        case "easyauth":
            from momentum.auth.easyauth import EasyAuthProvider

            return EasyAuthProvider(settings)
        case "host":
            if host_resolver is None:
                raise RuntimeError("AUTH_MODE=host requires mount_momentum(resolve_principal=...)")
            return HostAuthProvider(settings, host_resolver)
        case "oidc":
            raise NotImplementedError("oidc auth mode is planned; see ADR-0003")
    raise RuntimeError(f"unknown auth mode {settings.auth_mode}")
