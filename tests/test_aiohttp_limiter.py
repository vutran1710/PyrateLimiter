"""Tests for aiohttp_limiter close() method"""
import pytest
from pyrate_limiter import Limiter, Rate
from pyrate_limiter.extras.aiohttp_limiter import RateLimitedSession
from .conftest import DEFAULT_RATES


@pytest.mark.asyncio
async def test_close_method_closes_session():
    """Test that the close() method properly closes the aiohttp session."""
    limiter = Limiter(DEFAULT_RATES)
    session = RateLimitedSession(limiter)
    
    # Verify session is open
    assert not session._session.closed
    
    # Call close
    await session.close()
    
    # Verify session is closed
    assert session._session.closed


@pytest.mark.asyncio
async def test_close_idempotent():
    """Test that close() can be called multiple times without error."""
    limiter = Limiter(DEFAULT_RATES)
    session = RateLimitedSession(limiter)
    
    # Call close twice
    await session.close()
    await session.close()  # Should not raise


@pytest.mark.asyncio
async def test_close_after_context_manager():
    """Test that close() works after using the context manager."""
    limiter = Limiter(DEFAULT_RATES)
    
    async with RateLimitedSession(limiter) as session:
        assert not session._session.closed
    
    # Context manager already closed, close() should handle this gracefully
    assert session._session.closed
