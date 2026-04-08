"""apt_scrape.proxy — Pluggable proxy provider abstraction.

Supports IPRoyal residential proxies with automatic session rotation.
No local relay (pproxy) needed — IPRoyal supports HTTP proxy auth natively.
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Configuration for a proxy provider."""

    host: str
    port: int
    username: str
    password: str
    protocol: str = "http"  # "http" or "socks5"
    country: str = "it"  # Target country for geo-targeting
    sticky_session_minutes: int = 0  # 0 = rotating per request

    @classmethod
    def from_env(cls) -> "ProxyConfig | None":
        """Build config from IPROYAL_* environment variables.

        Returns None if required vars are not set.
        """
        host = os.getenv("IPROYAL_HOST", "").strip()
        port = os.getenv("IPROYAL_PORT", "12321").strip()
        user = os.getenv("IPROYAL_USER", "").strip()
        password = os.getenv("IPROYAL_PASS", "").strip()
        if not (host and user and password):
            return None
        return cls(
            host=host,
            port=int(port),
            username=user,
            password=password,
            protocol=os.getenv("IPROYAL_PROTOCOL", "http").strip(),
            country=os.getenv("IPROYAL_COUNTRY", "it").strip(),
            sticky_session_minutes=int(os.getenv("IPROYAL_STICKY_MINUTES", "0")),
        )


class ProxyProvider(ABC):
    """Abstract proxy provider interface."""

    @abstractmethod
    def get_proxy_url(self) -> str | None:
        """Return the current proxy URL, or None if no proxy."""

    def get_proxy_host_port(self) -> str | None:
        """Return scheme://host:port (no credentials) for --proxy-server flag."""
        return None

    def get_proxy_credentials(self) -> tuple[str, str] | None:
        """Return (username, password) or None if no auth needed."""
        return None

    @abstractmethod
    def rotate(self) -> None:
        """Force rotation to a new proxy/session."""

    @property
    @abstractmethod
    def proxy_count(self) -> int:
        """Number of available proxies (0 if no proxy)."""


class NoProxyProvider(ProxyProvider):
    """No-op provider for direct connections."""

    def get_proxy_url(self) -> str | None:
        return None

    def rotate(self) -> None:
        pass

    @property
    def proxy_count(self) -> int:
        return 0


class IPRoyalProvider(ProxyProvider):
    """IPRoyal residential proxy with session-based rotation.

    IPRoyal uses username suffixes to control sessions:
    - `user_session-<id>` for sticky sessions
    - New session ID = new IP

    No local relay needed — standard HTTP proxy auth.
    """

    def __init__(self, config: ProxyConfig) -> None:
        self._config = config
        self._session_id = self._new_session_id()
        self._base_password = config.password

    @staticmethod
    def _new_session_id() -> str:
        return uuid.uuid4().hex[:12]

    def _build_username(self) -> str:
        """Build username — use raw credentials (suffixes break IPRoyal auth)."""
        return self._config.username

    def get_proxy_url(self) -> str:
        username = self._build_username()
        return (
            f"{self._config.protocol}://{username}:{self._base_password}"
            f"@{self._config.host}:{self._config.port}"
        )

    def get_proxy_host_port(self) -> str:
        return f"{self._config.protocol}://{self._config.host}:{self._config.port}"

    def get_proxy_credentials(self) -> tuple[str, str]:
        return (self._build_username(), self._base_password)

    def rotate(self) -> None:
        old = self._session_id
        self._session_id = self._new_session_id()
        logger.info("Proxy session rotated: %s → %s", old[:6], self._session_id[:6])

    @property
    def proxy_count(self) -> int:
        return 1  # Residential pool acts as one rotating endpoint


def create_proxy_provider() -> ProxyProvider:
    """Factory: create the appropriate proxy provider from environment."""
    config = ProxyConfig.from_env()
    if config is None:
        logger.info("No proxy configured (set IPROYAL_* env vars to enable).")
        return NoProxyProvider()
    logger.info(
        "IPRoyal proxy enabled: %s:%d (country=%s)",
        config.host,
        config.port,
        config.country,
    )
    return IPRoyalProvider(config)
