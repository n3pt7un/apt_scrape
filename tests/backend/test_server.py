import pytest
import asyncio
from unittest.mock import AsyncMock, patch
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
