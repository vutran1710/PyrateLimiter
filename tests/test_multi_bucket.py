import logging
import time
import pytest
from pyrate_limiter import Limiter, Rate

logging.basicConfig(level=logging.INFO)

@pytest.mark.asyncio
async def test_delay_waiter_blocks_until_slot_available(create_bucket):

    bucket = await create_bucket(rates=[Rate(1, 1000), Rate(3, 5000)]) # 1 per sec, 3 per 5s
    limiter = Limiter(bucket) 

    t0 = time.time()
    assert await limiter.try_acquire_async("x")        # 1st ok
    assert await limiter.try_acquire_async("x")        # 2nd ok
    assert await limiter.try_acquire_async("x")        # 3rd ok

    start = time.time()
    ok = await limiter.try_acquire_async("x")
    elapsed = time.time() - start

    assert ok
    assert elapsed >= 2, f"returned too early, elapsed={elapsed:.2f}s"
