# ruff: noqa: T201
"""Token bucket (GCRA): constant-size state instead of a log per request.

Run: python examples/token_bucket.py
"""

from time import monotonic

from pyrate_limiter import Duration, Limiter, Rate, StateBucket, TokenBucket


def main() -> None:
    # 5 requests/second sustained, up to 10 spendable at once.
    rate = Rate(5, Duration.SECOND, burst=10)
    limiter = Limiter(StateBucket([rate], algorithm=TokenBucket()), buffer_ms=10)

    started = monotonic()

    # The burst goes straight through...
    burst = sum(1 for _ in range(20) if limiter.try_acquire("api", blocking=False))
    print(f"admitted {burst} immediately (burst={rate.burst})")

    # ...then the bucket drips at the sustained rate.
    for index in range(5):
        limiter.try_acquire("api", blocking=True)
        print(f"  request {index + 1} at {monotonic() - started:.2f}s")

    limiter.close()


if __name__ == "__main__":
    main()
