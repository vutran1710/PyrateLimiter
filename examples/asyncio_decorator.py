# ruff: noqa: T201
import asyncio
import logging
import time
from datetime import datetime

import pytest

from pyrate_limiter.limiter_factory import create_inmemory_limiter

logging.basicConfig(level=logging.DEBUG)


async def ticker():
    for _ in range(10):
        print(f"[TICK] {datetime.now()}")
        await asyncio.sleep(0.5)


def mapping(name, weight, i):
    return "mytask", 1


@pytest.mark.asyncio
async def test_asyncio_decorator():
    print("Running task_async using try_acquire_async and AsyncBucketWrapper")
    print("Note that the TICKs continue while the tasks are waiting")

    start = time.time()
    limiter = create_inmemory_limiter()

    @limiter.as_decorator(name="asyncio_test", weight=1)
    async def task_async(name: str, weight: int):
        print(f"try_acquire_async: {datetime.now()} {name}: {weight}")

    await asyncio.gather(ticker(), *[task_async("mytask", 1) for i in range(10)])
    print(f"Run 10 calls in {time.time() - start:,.2f} sec")


if __name__ == "__main__":
    asyncio.run(test_asyncio_decorator())
