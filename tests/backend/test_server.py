import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from apt_scrape.server import BrowserManager


@pytest.mark.asyncio
async def test_concurrent_ensure_browser():
    manager = BrowserManager()
    manager._browser = None

    # Mock _ensure_context to do nothing
    manager._ensure_context = AsyncMock()

    async def delayed_enter(*args, **kwargs):
        await asyncio.sleep(0.01)
        return AsyncMock()

    with patch('camoufox.async_api.AsyncCamoufox.__aenter__', new_callable=AsyncMock) as mock_aenter:
        mock_aenter.side_effect = delayed_enter

        # spawn 5 concurrent calls
        tasks = [manager._ensure_browser() for _ in range(5)]
        await asyncio.gather(*tasks)

        # lock should ensure exactly 1 instantiation
        assert mock_aenter.call_count == 1


@pytest.mark.asyncio
async def test_close_nulls_camoufox_ctx():
    """close() must reset _camoufox_ctx to None so stale references can't linger."""
    manager = BrowserManager()
    mock_ctx = AsyncMock()
    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True

    manager._browser = mock_browser
    manager._camoufox_ctx = mock_ctx
    manager._context = AsyncMock()

    await manager.close()

    assert manager._browser is None
    assert manager._camoufox_ctx is None
    assert manager._context is None
    mock_ctx.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_resets_state_even_when_aexit_fails():
    """If __aexit__ raises, browser and ctx should still be nulled."""
    manager = BrowserManager()
    mock_ctx = AsyncMock()
    mock_ctx.__aexit__.side_effect = RuntimeError("simulated crash")
    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True

    manager._browser = mock_browser
    manager._camoufox_ctx = mock_ctx
    manager._context = AsyncMock()

    await manager.close()

    assert manager._browser is None
    assert manager._camoufox_ctx is None


@pytest.mark.asyncio
async def test_parallel_reconnect_only_restarts_once():
    """When multiple parallel fetches detect connection loss, only one reconnect should happen."""
    manager = BrowserManager()
    manager._ensure_context = AsyncMock()

    # Track how many times close+ensure actually ran
    reconnect_count = 0
    original_close = manager._close_unlocked
    original_ensure = manager._ensure_browser_unlocked

    async def counting_close():
        nonlocal reconnect_count
        reconnect_count += 1
        manager._browser = None
        manager._camoufox_ctx = None
        manager._context = None

    async def fake_ensure():
        if manager._browser is not None:
            return
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        manager._browser = mock_browser
        manager._camoufox_ctx = AsyncMock()
        manager._context = AsyncMock()

    manager._close_unlocked = counting_close
    manager._ensure_browser_unlocked = fake_ensure

    # Simulate: browser exists but is_connected returns False (connection lost)
    dead_browser = MagicMock()
    dead_browser.is_connected.return_value = False
    manager._browser = dead_browser
    manager._camoufox_ctx = AsyncMock()
    manager._context = AsyncMock()

    async def simulate_reconnect():
        async with manager._browser_lock:
            if manager._browser is None or not manager._browser.is_connected():
                await manager._close_unlocked()
                await manager._ensure_browser_unlocked()

    # 5 concurrent reconnect attempts
    tasks = [simulate_reconnect() for _ in range(5)]
    await asyncio.gather(*tasks)

    # Lock serializes: first call reconnects, subsequent calls see healthy browser
    assert reconnect_count == 1
    assert manager._browser is not None


@pytest.mark.asyncio
async def test_close_is_idempotent():
    """Calling close() twice should not raise."""
    manager = BrowserManager()
    mock_ctx = AsyncMock()
    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True

    manager._browser = mock_browser
    manager._camoufox_ctx = mock_ctx
    manager._context = AsyncMock()

    await manager.close()
    await manager.close()  # second call should be a no-op

    assert manager._browser is None
    assert manager._camoufox_ctx is None
