import asyncio
import logging
import time
from datetime import datetime

from pyrate_limiter import Limiter
from pyrate_limiter.limiter_factory import create_inmemory_limiter
logging.basicConfig(level=logging.DEBUG)


async def ticker():
    for i in range(10):
        print(f"[TICK] {datetime.now()}")
        await asyncio.sleep(0.5)


def mapping(name, weight, i):
    return "mytask", 1


async def test_asyncio_ratelimit():
    print("Running task_async using try_acquire_async and BucketAsyncWrapper")
    print("Note that the TICKs continue while the tasks are waiting")

    start = time.time()
    limiter = create_inmemory_limiter(async_wrapper=True)

    async def task_async(name, weight, i, limiter: Limiter):
        await limiter.try_acquire_async(name, weight)

        print(f"try_acquire_async: {datetime.now()} {name}: {weight}")

    await asyncio.gather(ticker(), *[task_async(str(i), 1, i, limiter) for i in range(10)])
    print(f'Run 10 calls in {time.time() - start:,.2f} sec')


if __name__ == "__main__":
    asyncio.run(test_asyncio_ratelimit())
