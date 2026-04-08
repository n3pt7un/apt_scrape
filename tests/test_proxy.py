import pytest
from unittest.mock import patch
from apt_scrape.proxy import IPRoyalProvider, ProxyConfig, NoProxyProvider


def test_no_proxy_provider():
    provider = NoProxyProvider()
    assert provider.get_proxy_url() is None
    provider.rotate()  # no-op, should not raise
    assert provider.proxy_count == 0


def test_iproyal_config_from_env():
    with patch.dict("os.environ", {
        "IPROYAL_HOST": "geo.iproyal.com",
        "IPROYAL_PORT": "12321",
        "IPROYAL_USER": "myuser",
        "IPROYAL_PASS": "mypass",
    }):
        config = ProxyConfig.from_env()
        assert config.host == "geo.iproyal.com"
        assert config.port == 12321
        assert config.username == "myuser"


def test_iproyal_proxy_url():
    config = ProxyConfig(
        host="geo.iproyal.com",
        port=12321,
        username="user",
        password="pass",
        protocol="http",
    )
    provider = IPRoyalProvider(config)
    url = provider.get_proxy_url()
    # Raw credentials — no suffixes (suffixes break IPRoyal auth)
    assert url == "http://user:pass@geo.iproyal.com:12321"


def test_iproyal_host_port():
    config = ProxyConfig(
        host="geo.iproyal.com",
        port=12321,
        username="user",
        password="pass",
        protocol="http",
    )
    provider = IPRoyalProvider(config)
    assert provider.get_proxy_host_port() == "http://geo.iproyal.com:12321"
    assert provider.get_proxy_credentials() == ("user", "pass")


def test_iproyal_sticky_session():
    config = ProxyConfig(
        host="geo.iproyal.com",
        port=12321,
        username="user",
        password="pass",
        protocol="http",
        sticky_session_minutes=10,
    )
    provider = IPRoyalProvider(config)
    url1 = provider.get_proxy_url()
    url2 = provider.get_proxy_url()
    # Same session within the sticky window
    assert url1 == url2


def test_no_proxy_when_env_missing():
    with patch.dict("os.environ", {}, clear=True):
        config = ProxyConfig.from_env()
        assert config is None
