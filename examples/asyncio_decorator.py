import asyncio
import logging
import time
from datetime import datetime

from pyrate_limiter.limiter_factory import get_async_limiter
logging.basicConfig(level=logging.DEBUG)


async def ticker():
    for i in range(10):
        print(f"[TICK] {datetime.now()}")
        await asyncio.sleep(0.5)


def mapping(name, weight, i):
    return "mytask", 1


async def main():
    print("Running task_async using try_acquire_async and AsyncBucketWrapper")
    print("Note that the TICKs continue while the tasks are waiting")

    start = time.time()
    limiter = await get_async_limiter()

    @limiter.as_decorator()(lambda name, weight: (name, weight))  # type: ignore[arg-type]
    async def task_async(name: str, weight: int):
        print(f"try_acquire_async: {datetime.now()} {name}: {weight}")

    await asyncio.gather(ticker(), *[task_async("mytask", 1) for i in range(10)])
    print(f'Run 10 calls in {time.time() - start:,.2f} sec')


if __name__ == "__main__":
    asyncio.run(main())
